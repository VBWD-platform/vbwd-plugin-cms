"""Migration up/down/up for the pinned/sticky archive columns (real PG).

Additive, non-destructive migration adds ``pinned`` (Boolean NOT NULL, default
False) to BOTH ``cms_post`` (global blog-index pin) and ``cms_post_term``
(per-category pin). Validates: the revision chains off the current cms head,
upgrade adds both columns, existing rows default to ``false`` (non-destructive),
downgrade drops them, and a re-upgrade restores them — against a real connection
through alembic's Operations context, in isolation from the db fixture's
``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; chains within the cms plugin's own migration set; up/down/up
validated); SOLID/DI/DRY; Liskov (default False = the "not pinned" contract);
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import importlib.util
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "migrations",
        "versions",
        "20260708_1000_cms_post_pinned.py",
    )
    spec = importlib.util.spec_from_file_location("cms_post_pinned_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

pytestmark = pytest.mark.no_db_isolation

PINNED = "pinned"


def _has_column(connection, table: str, column: str) -> bool:
    return column in {col["name"] for col in inspect(connection).get_columns(table)}


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # create_all() already added the columns from the model; drop them so the
    # migration's upgrade runs against a pre-migration shape.
    if _has_column(connection, "cms_post_term", PINNED):
        operations.drop_column("cms_post_term", PINNED)
    if _has_column(connection, "cms_post", PINNED):
        operations.drop_column("cms_post", PINNED)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_cms_head(self):
        assert migration.revision == "20260708_cms_post_pinned"
        assert migration.down_revision == "20260707_cms_post_permalink"
        assert len(migration.revision) <= 32

    def test_upgrade_adds_both_pinned_columns(self, migration_connection):
        assert not _has_column(migration_connection, "cms_post", PINNED)
        assert not _has_column(migration_connection, "cms_post_term", PINNED)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert _has_column(migration_connection, "cms_post", PINNED)
        assert _has_column(migration_connection, "cms_post_term", PINNED)

    def test_existing_row_defaults_to_false(self, migration_connection):
        # A pre-existing post (column absent pre-upgrade) must come out unpinned.
        migration_connection.execute(
            text(
                "INSERT INTO cms_post (id, type, slug, title, content_json, "
                "status, language, robots, seo_excluded, sort_order, "
                "created_at, updated_at, version) VALUES "
                "(gen_random_uuid(), 'post', 'pinned-mig-existing', 'T', "
                "'{}'::json, 'draft', 'en', 'index,follow', false, 0, now(), "
                "now(), 0)"
            )
        )
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        value = migration_connection.execute(
            text("SELECT pinned FROM cms_post WHERE slug = 'pinned-mig-existing'")
        ).scalar()
        assert value is False

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert not _has_column(migration_connection, "cms_post", PINNED)
        assert not _has_column(migration_connection, "cms_post_term", PINNED)
        with Operations.context(context):
            migration.upgrade()
        assert _has_column(migration_connection, "cms_post", PINNED)
        assert _has_column(migration_connection, "cms_post_term", PINNED)
