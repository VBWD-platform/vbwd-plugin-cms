"""Migration up/down/up for the cms_layout.is_default column (real PG).

Additive migration adds ``is_default`` + a partial unique index to
``cms_layout`` (mirroring 20260420_1000_style_default for cms_style).
Validates upgrade adds the column + index, the downgrade drops them, and a
re-upgrade restores them — against a real connection through alembic's
Operations context, in isolation from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves within the cms plugin's own migration chain;
up/down/up validated); SOLID/DI/DRY; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
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
        "20260606_1100_cms_layout_default.py",
    )
    spec = importlib.util.spec_from_file_location("cms_layout_default_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

COLUMN = "is_default"
INDEX = "ix_cms_layout_default_singleton"


def _column_names(connection):
    return {col["name"] for col in inspect(connection).get_columns("cms_layout")}


def _index_names(connection):
    return {idx["name"] for idx in inspect(connection).get_indexes("cms_layout")}


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
    # The db fixture's create_all() already added the column; drop it so the
    # migration's upgrade runs against a pre-migration shape.
    if INDEX in _index_names(connection):
        operations.drop_index(INDEX, table_name="cms_layout")
    if COLUMN in _column_names(connection):
        operations.drop_column("cms_layout", COLUMN)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_cms_head(self):
        assert migration.revision == "20260606_1100_cms_layout_default"
        assert migration.down_revision == "20260606_cms_post_areas_widgets"
        assert len(migration.revision) <= 32

    def test_upgrade_adds_column_and_index(self, migration_connection):
        assert COLUMN not in _column_names(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMN in _column_names(migration_connection)
        assert INDEX in _index_names(migration_connection)

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert COLUMN not in _column_names(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMN in _column_names(migration_connection)
        assert INDEX in _index_names(migration_connection)
