"""Migration up/down/up validation for the unified content tables (S47.0).

Binds the migration's upgrade/downgrade to a real connection through
alembic's Operations context and asserts the three tables appear, drop,
and reappear cleanly. The ``db`` fixture's ``create_all`` already created
these tables, so we drop them first to exercise the migration in isolation.
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
        "20260603_1000_cms_unified_post.py",
    )
    spec = importlib.util.spec_from_file_location("cms_unified_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

UNIFIED_TABLES = ("cms_post", "cms_term", "cms_post_term")


def _table_names(connection):
    return set(inspect(connection).get_table_names())


@pytest.fixture
def migration_connection(app):
    # Depend on ``app`` (schema built once), not ``db`` — this fixture opens
    # its OWN connection + transaction and rolls back at teardown, so it
    # self-cleans without the rolled-back-session isolation (which would swap
    # ``db.engine`` for a Connection and break ``db.engine.connect()`` below).
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    # Start from a clean slate: the db fixture's create_all() already made
    # these tables, so drop them before exercising the migration. Use CASCADE
    # so we stay robust to tables OTHER plugins FK onto the unified tables
    # without this test needing to know about them — e.g. the dataset plugin's
    # ``dataset_term.term_id -> cms_term`` junction in the aggregated CI DB.
    # Everything runs inside ``transaction`` and is rolled back at teardown, so
    # cascading away a foreign table here has no lasting effect.
    from sqlalchemy import text

    for table in (
        "cms_post_widget",
        "cms_post_content_block",
        "cms_post_term",
        "cms_term",
        "cms_post",
    ):
        if table in _table_names(connection):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_upgrade_creates_tables(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        present = _table_names(migration_connection)
        for table in UNIFIED_TABLES:
            assert table in present

    def test_downgrade_drops_tables(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        present = _table_names(migration_connection)
        for table in UNIFIED_TABLES:
            assert table not in present

    def test_up_down_up_is_clean(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        present = _table_names(migration_connection)
        for table in UNIFIED_TABLES:
            assert table in present
