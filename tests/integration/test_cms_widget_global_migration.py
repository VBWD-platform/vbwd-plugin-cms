"""Migration up/down/up for dropping cms_widget.is_global (real PG).

The site-wide "global widget" feature was removed; this migration DROPs the
``is_global`` column. ``upgrade`` removes the column, ``downgrade`` re-adds it
(nullable, default false) for reversibility, and a re-upgrade removes it again
— validated against a real connection through alembic's Operations context, in
isolation from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves within the cms plugin's own migration chain;
up/down/up validated); SOLID/DI/DRY; no overengineering. Quality guard:
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
        "20260612_1100_drop_widget_global.py",
    )
    spec = importlib.util.spec_from_file_location(
        "cms_widget_drop_global_migration", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

COLUMN = "is_global"


def _column_names(connection):
    return {col["name"] for col in inspect(connection).get_columns("cms_widget")}


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
    # The model no longer carries the column, so create_all() did not add it.
    # Re-create the pre-migration shape so the drop migration has something to
    # drop.
    if COLUMN not in _column_names(connection):
        operations.add_column(
            "cms_widget",
            sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_prior_cms_head(self):
        assert migration.revision == "20260612_1100_drop_widget_global"
        assert migration.down_revision == "20260612_1000_cms_widget_global"
        assert len(migration.revision) <= 32

    def test_upgrade_drops_column(self, migration_connection):
        assert COLUMN in _column_names(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMN not in _column_names(migration_connection)

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            assert COLUMN not in _column_names(migration_connection)
            migration.downgrade()
        assert COLUMN in _column_names(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMN not in _column_names(migration_connection)
