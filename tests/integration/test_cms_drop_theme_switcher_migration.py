"""Migration up/down/up for dropping ``use_theme_switcher_styles`` (real PG).

The legacy theme-switcher flag is removed from ``cms_post`` and ``cms_page``.
Validates the upgrade drops the column from both tables, the downgrade restores
it, and a re-upgrade drops it again — all against a real connection through
alembic's Operations context, isolated from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves standalone within the cms plugin's own migration
chain; up/down/up validated); SOLID/DI/DRY; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import importlib.util
import os

import pytest
import sqlalchemy as sa
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
        "20260604_1000_drop_theme_switcher.py",
    )
    spec = importlib.util.spec_from_file_location("cms_drop_theme_switcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

TABLES = ("cms_post", "cms_page")
COLUMN = "use_theme_switcher_styles"


def _has_column(connection, table):
    return COLUMN in {col["name"] for col in inspect(connection).get_columns(table)}


@pytest.fixture
def migration_connection(app):
    # Depend on ``app`` (schema built once), not ``db`` — this fixture opens
    # its OWN connection + transaction and rolls back at teardown, so it
    # self-cleans without the rolled-back-session isolation (which would swap
    # ``db.engine`` for a Connection and break ``db.engine.connect()`` below).
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # The model no longer declares the column, so create_all() omits it; add it
    # back so the migration's upgrade runs against the pre-drop shape.
    for table in TABLES:
        if not _has_column(connection, table):
            operations.add_column(
                table,
                sa.Column(
                    COLUMN, sa.Boolean(), nullable=False, server_default=sa.true()
                ),
            )
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestDropThemeSwitcherMigration:
    def test_revision_chains_off_layout_head(self):
        assert migration.revision == "20260604_drop_theme_switcher"
        assert migration.down_revision == "20260603_1200_cms_post_layout"
        assert len(migration.revision) <= 32

    def test_upgrade_drops_column_from_both_tables(self, migration_connection):
        for table in TABLES:
            assert _has_column(migration_connection, table)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        for table in TABLES:
            assert not _has_column(migration_connection, table)

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        for table in TABLES:
            assert _has_column(migration_connection, table)
        with Operations.context(context):
            migration.upgrade()
        for table in TABLES:
            assert not _has_column(migration_connection, table)
