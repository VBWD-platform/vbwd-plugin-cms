"""S77 D7 — fold CMS tags into the core tag tables, then drop the old ones.

The CMS plugin migration ``20260613_1300_fold_tags`` runs AFTER the core
``vbwd_tag`` / ``vbwd_entity_tag`` migration (``20260613_1200_tags_cf``) and the
prior cms head (``20260612_1100_drop_widget_global``). It reimports every
``cms_term(term_type='tag')`` + its ``cms_post_term`` links into ``vbwd_tag`` /
``vbwd_entity_tag`` (scoped ``parent_entity_type='cms_post'``, entity_type
``cms_post``), verifies the link counts match, then drops the tag terms + their
links. Categories (``cms_term(term_type='category')``) and their links are left
untouched. Idempotent (``ON CONFLICT DO NOTHING``) so a re-run is safe.

Engineering requirements (binding, restated): TDD-first (this RED-first guard
asserts the reimport+drop contract before the migration exists); DevOps-first
(schema/data change only via Alembic; resolves within the cms chain anchored on
the core tags revision; up/down/up validated against real PG); SOLID/DI/DRY
(set-based SQL, single home for the move); Liskov; clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import importlib.util
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "migrations",
        "versions",
        "20260613_1300_fold_tags_into_core.py",
    )
    spec = importlib.util.spec_from_file_location("cms_fold_tags_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation


def _insert_term(conn, term_type, slug, name):
    term_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO cms_term
                (id, term_type, slug, name, seo_excluded, sort_order,
                 created_at, updated_at, version)
            VALUES (:id, :term_type, :slug, :name, false, 0,
                    now(), now(), 0)
            """
        ),
        {"id": term_id, "term_type": term_type, "slug": slug, "name": name},
    )
    return term_id


def _insert_post(conn, slug):
    post_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO cms_post
                (id, type, slug, title, status, content_json,
                 language, sort_order, robots, seo_excluded,
                 created_at, updated_at, version)
            VALUES (:id, 'post', :slug, :title, 'published', '{}'::json,
                    'en', 0, 'index,follow', false,
                    now(), now(), 0)
            """
        ),
        {"id": post_id, "slug": slug, "title": slug},
    )
    return post_id


def _link(conn, post_id, term_id):
    conn.execute(
        sa.text(
            """
            INSERT INTO cms_post_term
                (id, post_id, term_id, created_at, updated_at, version)
            VALUES (:id, :post_id, :term_id, now(), now(), 0)
            """
        ),
        {"id": uuid.uuid4(), "post_id": post_id, "term_id": term_id},
    )


def _count(conn, sql, params=None):
    return conn.execute(sa.text(sql), params or {}).scalar()


@pytest.fixture
def seeded(app):
    """Seed pre-migration state on a rolled-back connection.

    Two tag terms (one shared across two posts, one on one post) + one category
    term (also linked) — so we can assert tags move and categories don't.

    Depends on ``app`` (schema built once), not ``db`` — this fixture opens its
    OWN connection + transaction and rolls back at teardown, so it self-cleans
    without the rolled-back-session isolation (which would swap ``db.engine`` for
    a Connection and break ``db.engine.connect()`` below).
    """
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    suffix = uuid.uuid4().hex[:8]

    tag_news = _insert_term(connection, "tag", f"news-{suffix}", "News")
    tag_python = _insert_term(connection, "tag", f"python-{suffix}", "Python")
    category = _insert_term(connection, "category", f"guides-{suffix}", "Guides")

    post_one = _insert_post(connection, f"post-one-{suffix}")
    post_two = _insert_post(connection, f"post-two-{suffix}")

    # tag_news on both posts, tag_python on post_one, category on post_two.
    _link(connection, post_one, tag_news)
    _link(connection, post_two, tag_news)
    _link(connection, post_one, tag_python)
    _link(connection, post_two, category)

    state = {
        "connection": connection,
        "suffix": suffix,
        "tag_slugs": {f"news-{suffix}", f"python-{suffix}"},
        "category_slug": f"guides-{suffix}",
        "category_id": category,
        "post_one": post_one,
        "post_two": post_two,
        "tag_link_count": 3,  # news×2 + python×1
    }
    try:
        yield state
    finally:
        transaction.rollback()
        connection.close()


class TestRevisionChain:
    def test_revision_and_anchors(self):
        assert migration.revision == "20260613_1300_fold_tags"
        # Merge node: anchors on the prior cms head AND the core tags revision.
        assert isinstance(migration.down_revision, tuple)
        assert "20260612_1100_drop_widget_global" in migration.down_revision
        assert "20260613_1200_tags_cf" in migration.down_revision
        assert len(migration.revision) <= 32


class TestUpgrade:
    def _upgrade(self, connection):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

    def test_tags_move_into_core_with_matching_counts(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        # Every old tag term is now a cms_post-scoped catalog row.
        for slug in seeded["tag_slugs"]:
            scope = _count(
                conn,
                "SELECT parent_entity_type FROM vbwd_tag WHERE slug = :slug",
                {"slug": slug},
            )
            assert scope == "cms_post"

        # entity_tag rows == old tag-typed cms_post_term rows (3).
        moved = _count(
            conn,
            "SELECT count(*) FROM vbwd_entity_tag WHERE entity_type = 'cms_post' "
            "AND tag_slug = ANY(:slugs)",
            {"slugs": list(seeded["tag_slugs"])},
        )
        assert moved == seeded["tag_link_count"]

        # post_one carries both tags, post_two carries the shared tag.
        one = _count(
            conn,
            "SELECT count(*) FROM vbwd_entity_tag WHERE entity_id = :pid",
            {"pid": seeded["post_one"]},
        )
        assert one == 2

    def test_old_tag_rows_and_links_dropped(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        assert (
            _count(conn, "SELECT count(*) FROM cms_term WHERE term_type = 'tag'") == 0
        )
        # No cms_post_term row references a tag term any more.
        orphan_tag_links = _count(
            conn,
            "SELECT count(*) FROM cms_post_term link "
            "JOIN cms_term term ON term.id = link.term_id "
            "WHERE term.term_type = 'tag'",
        )
        assert orphan_tag_links == 0

    def test_categories_untouched(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        # The category term survives with its link to post_two.
        assert (
            _count(
                conn,
                "SELECT count(*) FROM cms_term WHERE slug = :slug",
                {"slug": seeded["category_slug"]},
            )
            == 1
        )
        assert (
            _count(
                conn,
                "SELECT count(*) FROM cms_post_term WHERE term_id = :tid",
                {"tid": seeded["category_id"]},
            )
            == 1
        )
        # cms_term now holds categories only.
        assert (
            _count(conn, "SELECT count(*) FROM cms_term WHERE term_type != 'category'")
            == 0
        )

    def test_idempotent_on_rerun(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)
        moved_first = _count(
            conn,
            "SELECT count(*) FROM vbwd_entity_tag WHERE tag_slug = ANY(:slugs)",
            {"slugs": list(seeded["tag_slugs"])},
        )
        # Re-running the (now-empty-source) migration must not error or duplicate.
        self._upgrade(conn)
        moved_second = _count(
            conn,
            "SELECT count(*) FROM vbwd_entity_tag WHERE tag_slug = ANY(:slugs)",
            {"slugs": list(seeded["tag_slugs"])},
        )
        assert moved_first == moved_second == seeded["tag_link_count"]


class TestDownUp:
    def test_down_recreates_tag_terms_then_up_drops_again(self, seeded):
        conn = seeded["connection"]
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            migration.upgrade()
            assert (
                _count(conn, "SELECT count(*) FROM cms_term WHERE term_type='tag'") == 0
            )
            migration.downgrade()
        # Best-effort reverse: the tag terms + links are recreated.
        assert _count(
            conn, "SELECT count(*) FROM cms_term WHERE term_type='tag'"
        ) == len(seeded["tag_slugs"])
        recreated_links = _count(
            conn,
            "SELECT count(*) FROM cms_post_term link "
            "JOIN cms_term term ON term.id = link.term_id "
            "WHERE term.term_type = 'tag'",
        )
        assert recreated_links == seeded["tag_link_count"]
        with Operations.context(context):
            migration.upgrade()
        assert _count(conn, "SELECT count(*) FROM cms_term WHERE term_type='tag'") == 0
