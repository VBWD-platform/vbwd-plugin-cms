"""S77 reversal — unfold CMS tags from the core catalog back into the taxonomy.

Reverses the ``20260613_1300_fold_tags`` data move: every ``cms_post``-scoped
``vbwd_tag`` row (with its ``vbwd_entity_tag`` links to cms_post/cms_page
entities) is restored as a ``cms_term(term_type='tag')`` plus ``cms_post_term``
links, then the migrated cms_post-scoped catalog rows are removed so tags are
not duplicated across both systems. Tags scoped to OTHER entity types (products
etc.) are left untouched.

Engineering requirements (binding, restated): TDD-first (this RED-first guard
asserts the unfold contract before the migration exists); DevOps-first (data
change only via Alembic; resolves within the cms chain; up/down validated
against real PG); SOLID/DI/DRY (set-based, idempotent SQL, single home for the
move); Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
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
        "20260618_1000_unfold_tags_from_core.py",
    )
    spec = importlib.util.spec_from_file_location("cms_unfold_tags_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation.
pytestmark = pytest.mark.no_db_isolation


def _insert_tag(conn, slug, name, parent_entity_type):
    tag_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO vbwd_tag
                (id, slug, name, parent_entity_type, meta_data, color,
                 created_at, updated_at, version)
            VALUES (:id, :slug, :name, :scope, '{}'::jsonb, NULL,
                    now(), now(), 0)
            """
        ),
        {"id": tag_id, "slug": slug, "name": name, "scope": parent_entity_type},
    )
    return tag_id


def _insert_entity_tag(conn, entity_type, entity_id, tag_slug):
    conn.execute(
        sa.text(
            """
            INSERT INTO vbwd_entity_tag (entity_type, entity_id, tag_slug)
            VALUES (:entity_type, :entity_id, :tag_slug)
            """
        ),
        {"entity_type": entity_type, "entity_id": entity_id, "tag_slug": tag_slug},
    )


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


def _count(conn, sql, params=None):
    return conn.execute(sa.text(sql), params or {}).scalar()


@pytest.fixture
def seeded(app):
    """Seed post-fold state: cms_post-scoped tags + entity_tag links, plus a
    product-scoped tag that must NOT be touched.

    Opens its OWN connection + transaction and rolls back at teardown.
    """
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    suffix = uuid.uuid4().hex[:8]

    post_one = _insert_post(connection, f"post-one-{suffix}")
    post_two = _insert_post(connection, f"post-two-{suffix}")

    cms_tag_slug = f"news-{suffix}"
    other_cms_tag_slug = f"python-{suffix}"
    product_tag_slug = f"sale-{suffix}"

    _insert_tag(connection, cms_tag_slug, "News", "cms_post")
    _insert_tag(connection, other_cms_tag_slug, "Python", "cms_post")
    # A tag scoped to a different entity type — must survive untouched.
    _insert_tag(connection, product_tag_slug, "Sale", "product")

    # news on both posts, python on post_one; product tag on some product entity.
    _insert_entity_tag(connection, "cms_post", post_one, cms_tag_slug)
    _insert_entity_tag(connection, "cms_post", post_two, cms_tag_slug)
    _insert_entity_tag(connection, "cms_post", post_one, other_cms_tag_slug)
    _insert_entity_tag(connection, "product", uuid.uuid4(), product_tag_slug)

    state = {
        "connection": connection,
        "suffix": suffix,
        "cms_tag_slug": cms_tag_slug,
        "other_cms_tag_slug": other_cms_tag_slug,
        "product_tag_slug": product_tag_slug,
        "post_one": post_one,
        "post_two": post_two,
        "cms_tag_link_count": 3,  # news×2 + python×1
    }
    try:
        yield state
    finally:
        transaction.rollback()
        connection.close()


class TestRevisionChain:
    def test_revision_and_anchor(self):
        assert migration.revision == "20260618_unfold_tags"
        # Chains off the current cms head.
        assert migration.down_revision == "20260617_cms_pw_config_override"
        assert len(migration.revision) <= 32


class TestUpgrade:
    def _upgrade(self, connection):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

    def test_cms_tags_restored_as_terms_and_links(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        # Every cms_post-scoped tag is now a cms_term('tag').
        for slug in (seeded["cms_tag_slug"], seeded["other_cms_tag_slug"]):
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM cms_term "
                    "WHERE term_type = 'tag' AND slug = :slug",
                    {"slug": slug},
                )
                == 1
            )

        # cms_post_term links == old cms_post-scoped entity_tag links (3).
        restored_links = _count(
            conn,
            "SELECT count(*) FROM cms_post_term link "
            "JOIN cms_term term ON term.id = link.term_id "
            "WHERE term.term_type = 'tag'",
        )
        assert restored_links == seeded["cms_tag_link_count"]

        # post_one carries both tags.
        one = _count(
            conn,
            "SELECT count(*) FROM cms_post_term WHERE post_id = :pid",
            {"pid": seeded["post_one"]},
        )
        assert one == 2

    def test_migrated_core_catalog_rows_removed(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        # The cms_post-scoped catalog rows + links are gone.
        assert (
            _count(
                conn,
                "SELECT count(*) FROM vbwd_tag WHERE parent_entity_type = 'cms_post'",
            )
            == 0
        )
        assert (
            _count(
                conn,
                "SELECT count(*) FROM vbwd_entity_tag "
                "WHERE entity_type IN ('cms_post', 'cms_page')",
            )
            == 0
        )

    def test_non_cms_tags_untouched(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)

        # The product-scoped tag + its link survive.
        assert (
            _count(
                conn,
                "SELECT count(*) FROM vbwd_tag WHERE slug = :slug",
                {"slug": seeded["product_tag_slug"]},
            )
            == 1
        )
        assert (
            _count(
                conn,
                "SELECT count(*) FROM vbwd_entity_tag WHERE entity_type = 'product'",
            )
            == 1
        )
        # It did NOT become a cms_term.
        assert (
            _count(
                conn,
                "SELECT count(*) FROM cms_term WHERE slug = :slug",
                {"slug": seeded["product_tag_slug"]},
            )
            == 0
        )

    def test_idempotent_on_rerun(self, seeded):
        conn = seeded["connection"]
        self._upgrade(conn)
        first = _count(
            conn,
            "SELECT count(*) FROM cms_post_term link "
            "JOIN cms_term term ON term.id = link.term_id "
            "WHERE term.term_type = 'tag'",
        )
        # Re-running (now-empty-source) must not error or duplicate.
        self._upgrade(conn)
        second = _count(
            conn,
            "SELECT count(*) FROM cms_post_term link "
            "JOIN cms_term term ON term.id = link.term_id "
            "WHERE term.term_type = 'tag'",
        )
        assert first == second == seeded["cms_tag_link_count"]


class TestDownUp:
    def test_down_refolds_then_up_unfolds_again(self, seeded):
        conn = seeded["connection"]
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            migration.upgrade()
            assert (
                _count(
                    conn,
                    "SELECT count(*) FROM cms_term WHERE term_type = 'tag'",
                )
                == 2
            )
            migration.downgrade()
        # Best-effort reverse: the cms_post-scoped catalog rows + links return.
        assert (
            _count(
                conn,
                "SELECT count(*) FROM vbwd_tag WHERE parent_entity_type = 'cms_post'",
            )
            == 2
        )
        refolded_links = _count(
            conn,
            "SELECT count(*) FROM vbwd_entity_tag WHERE entity_type = 'cms_post'",
        )
        assert refolded_links == seeded["cms_tag_link_count"]
        with Operations.context(context):
            migration.upgrade()
        assert (
            _count(conn, "SELECT count(*) FROM cms_term WHERE term_type = 'tag'") == 2
        )
