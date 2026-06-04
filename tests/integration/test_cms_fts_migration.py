"""Migration up/down/up validation for the FTS search column (S47.4, real PG).

The 20260603_1100 migration adds the generated ``search_vector`` tsvector
column + GIN index to ``cms_post``. The ``db`` fixture's create_all() already
made the column (declared on the model), so we drop it first to exercise the
migration in isolation, then assert it (and its index) appear, drop, reappear.
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
        "20260603_1100_cms_post_search_vector.py",
    )
    spec = importlib.util.spec_from_file_location("cms_search_vector_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

COLUMN = "search_vector"
INDEX = "ix_cms_post_search_vector"


def _column_names(connection):
    return {col["name"] for col in inspect(connection).get_columns("cms_post")}


def _index_names(connection):
    return {idx["name"] for idx in inspect(connection).get_indexes("cms_post")}


@pytest.fixture
def migration_connection(db):
    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # create_all() already added the generated column + index; drop them so the
    # migration runs against a clean cms_post (sans search_vector).
    if INDEX in _index_names(connection):
        operations.drop_index(INDEX, table_name="cms_post")
    if COLUMN in _column_names(connection):
        operations.drop_column("cms_post", COLUMN)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_upgrade_adds_column_and_index(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMN in _column_names(migration_connection)
        assert INDEX in _index_names(migration_connection)

    def test_downgrade_drops_column_and_index(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert COLUMN not in _column_names(migration_connection)
        assert INDEX not in _index_names(migration_connection)

    def test_up_down_up_is_clean(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        assert COLUMN in _column_names(migration_connection)
        assert INDEX in _index_names(migration_connection)
