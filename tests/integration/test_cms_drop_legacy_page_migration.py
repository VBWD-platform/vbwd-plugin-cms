"""Migration up/down/up validation for the S105 legacy-page drop (real PG).

The migration's ``upgrade()`` DROPS the retired ``cms_page`` / ``cms_category`` /
``cms_page_widget`` / ``cms_page_content_block`` tables; ``downgrade()`` recreates
them. The retired models are deleted, so the ``db`` fixture's ``create_all`` no
longer makes these tables — the fixture seeds them by running the migration's own
``downgrade()`` first, then the test exercises up (drop) → down (recreate) → up
(drop) in isolation.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves standalone within the cms plugin's own migration
chain; up/down/up validated); SOLID/DI/DRY; Liskov; clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import importlib.util
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "migrations",
        "versions",
        "20260625_1000_drop_legacy_cms_page_subsystem.py",
    )
    spec = importlib.util.spec_from_file_location("cms_drop_legacy_page", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

LEGACY_TABLES = (
    "cms_page_widget",
    "cms_page_content_block",
    "cms_page",
    "cms_category",
)


def _table_names(connection):
    return set(inspect(connection).get_table_names())


@pytest.fixture
def migration_connection(app):
    # Depend on ``app`` (schema built once), not ``db`` — this fixture opens its
    # OWN connection + transaction and rolls back at teardown. The legacy models
    # are deleted, so create_all() did NOT make these tables; seed them by
    # running the migration's own downgrade() so the upgrade has something to
    # drop. Drop any leftovers first to start from a known state.
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        for table in LEGACY_TABLES:
            if table in _table_names(connection):
                Operations(context).drop_table(table)
        # Seed the legacy tables via the migration's own recreate path.
        migration.downgrade()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestDropLegacyPageMigration:
    def test_revision_chains_off_unfold_tags_head(self):
        assert migration.revision == "20260625_drop_legacy_cms_page"
        assert migration.down_revision == "20260618_unfold_tags"
        assert len(migration.revision) <= 32

    def test_upgrade_drops_legacy_tables(self, migration_connection):
        for table in LEGACY_TABLES:
            assert table in _table_names(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        present = _table_names(migration_connection)
        for table in LEGACY_TABLES:
            assert table not in present

    def test_downgrade_recreates_legacy_tables(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        present = _table_names(migration_connection)
        for table in LEGACY_TABLES:
            assert table in present

    def test_up_down_up_is_clean(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        present = _table_names(migration_connection)
        for table in LEGACY_TABLES:
            assert table not in present

    def test_upgrade_is_idempotent_on_legacy_free_db(self, migration_connection):
        # Drop everything, then upgrade again — the IF EXISTS guard must make a
        # second upgrade a no-op rather than erroring on a missing table.
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.upgrade()
        present = _table_names(migration_connection)
        for table in LEGACY_TABLES:
            assert table not in present
