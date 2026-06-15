"""Migration up/down/up for the cms_post layout/style columns (real PG).

Additive migration adds ``layout_id`` / ``style_id`` / ``use_theme_switcher_styles``
to ``cms_post`` (mirroring cms_page). Validates upgrade adds the columns, the
downgrade drops them, and a re-upgrade restores them — all against a real
connection through alembic's Operations context, in isolation from the db
fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves standalone within the cms plugin's own migration
chain; up/down/up validated); SOLID/DI/DRY; no overengineering. Quality guard:
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
        "20260603_1200_cms_post_layout.py",
    )
    spec = importlib.util.spec_from_file_location("cms_post_layout_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

NEW_COLUMNS = ("layout_id", "style_id", "use_theme_switcher_styles")


def _column_names(connection):
    return {col["name"] for col in inspect(connection).get_columns("cms_post")}


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
    # The db fixture's create_all() already added the columns; drop them so the
    # migration's upgrade runs against a pre-migration shape.
    for column in NEW_COLUMNS:
        if column in _column_names(connection):
            operations.drop_column("cms_post", column)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_search_vector_head(self):
        assert migration.revision == "20260603_1200_cms_post_layout"
        assert migration.down_revision == "20260603_1100_cms_search_vec"
        assert len(migration.revision) <= 32

    def test_upgrade_adds_columns(self, migration_connection):
        for column in NEW_COLUMNS:
            assert column not in _column_names(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        for column in NEW_COLUMNS:
            assert column in _column_names(migration_connection)

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        for column in NEW_COLUMNS:
            assert column not in _column_names(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        for column in NEW_COLUMNS:
            assert column in _column_names(migration_connection)
