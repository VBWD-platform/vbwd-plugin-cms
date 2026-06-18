"""Migration up/down/up for cms_post_widget.config_override (real PG).

Validates the upgrade adds the column, the downgrade drops it, and a re-upgrade
restores it — against a real connection through alembic's Operations context,
isolated from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; resolves standalone within the cms plugin's chain; up/down/up
validated); no overengineering. Quality guard:
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
        "20260617_1000_cms_post_widget_config_override.py",
    )
    spec = importlib.util.spec_from_file_location("cms_pw_config_override", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

# These tests open their OWN connection off a real ``db.engine`` and roll it
# back themselves, so they must run WITHOUT the rolled-back-session isolation
# (which swaps ``db.engine`` for a Connection, breaking ``db.engine.connect()``).
pytestmark = pytest.mark.no_db_isolation

TABLE = "cms_post_widget"
COLUMN = "config_override"


def _has_column(connection):
    return COLUMN in {col["name"] for col in inspect(connection).get_columns(TABLE)}


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # create_all() already added the column; drop it so upgrade runs clean.
    if _has_column(connection):
        operations.drop_column(TABLE, COLUMN)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestPostWidgetConfigOverrideMigration:
    def test_revision_chains_off_fold_tags(self):
        assert migration.revision == "20260617_cms_pw_config_override"
        assert migration.down_revision == "20260613_1300_fold_tags"
        assert len(migration.revision) <= 32

    def test_up_down_up(self, migration_connection):
        assert not _has_column(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert _has_column(migration_connection)
        with Operations.context(context):
            migration.downgrade()
        assert not _has_column(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert _has_column(migration_connection)
