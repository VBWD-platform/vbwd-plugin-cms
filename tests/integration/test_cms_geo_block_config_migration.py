"""Migration up/down/up for the cms_geo_block_config table (real PG, S120).

Additive migration creates the singleton ``cms_geo_block_config`` table. Validates
upgrade creates it, downgrade drops it, and a re-upgrade restores it — against a
real connection through alembic's Operations context, in isolation from the db
fixture's ``create_all``.

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
        "20260706_1000_cms_geo_block_config.py",
    )
    spec = importlib.util.spec_from_file_location("cms_geo_block_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

TABLE = "cms_geo_block_config"


def _table_names(connection):
    return set(inspect(connection).get_table_names())


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # The db fixture's create_all() already created the table; drop it so the
    # migration's upgrade runs against a pre-migration shape.
    if TABLE in _table_names(connection):
        operations.drop_table(TABLE)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_cms_head(self):
        assert migration.revision == "20260706_cms_geo_block_config"
        assert migration.down_revision == "20260705_cms_layout_head_html"
        assert len(migration.revision) <= 32

    def test_upgrade_creates_table(self, migration_connection):
        assert TABLE not in _table_names(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert TABLE in _table_names(migration_connection)

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert TABLE not in _table_names(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert TABLE in _table_names(migration_connection)
