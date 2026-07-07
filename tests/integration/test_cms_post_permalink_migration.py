"""Migration up/down/up for cms_post permalink columns (real PG, S122).

Additive migration adds ``slug_base`` + ``primary_term_id`` to ``cms_post`` and
backfills ``slug_base`` to the last path segment of the existing ``slug``.
Validates upgrade adds the columns (+ backfill), downgrade drops them, and a
re-upgrade restores them — against a real connection through alembic's
Operations context, in isolation from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; chains within the cms plugin's own migration set; up/down/up
validated); SOLID/DI/DRY; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
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
        "20260707_1000_cms_post_permalink.py",
    )
    spec = importlib.util.spec_from_file_location("cms_post_permalink_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

pytestmark = pytest.mark.no_db_isolation

TABLE = "cms_post"
COLUMNS = {"slug_base", "primary_term_id"}


def _columns(connection):
    return {col["name"] for col in inspect(connection).get_columns(TABLE)}


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # create_all() already added the columns from the model; drop them so the
    # migration's upgrade runs against a pre-migration shape. Dropping a column
    # cascades its FK/index in Postgres, so no explicit constraint drop is needed
    # (create_all names the FK differently than the migration anyway).
    existing = _columns(connection)
    if "primary_term_id" in existing:
        operations.drop_column(TABLE, "primary_term_id")
    if "slug_base" in existing:
        operations.drop_column(TABLE, "slug_base")
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_cms_head(self):
        assert migration.revision == "20260707_cms_post_permalink"
        assert migration.down_revision == "20260706_cms_geo_block_config"
        assert len(migration.revision) <= 32

    def test_upgrade_adds_columns(self, migration_connection):
        assert not COLUMNS & _columns(migration_connection)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMNS <= _columns(migration_connection)

    def test_upgrade_backfills_slug_base_last_segment(self, migration_connection):
        # A row with a nested slug (columns are absent pre-upgrade).
        migration_connection.execute(
            text(
                "INSERT INTO cms_post (id, type, slug, title, content_json, "
                "status, language, robots, seo_excluded, sort_order, "
                "created_at, updated_at, version) VALUES "
                "(gen_random_uuid(), 'post', 'blog/electronics/my-post', 'T', "
                "'{}'::json, 'draft', 'en', 'index,follow', false, 0, now(), "
                "now(), 0)"
            )
        )
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        value = migration_connection.execute(
            text(
                "SELECT slug_base FROM cms_post WHERE slug = "
                "'blog/electronics/my-post'"
            )
        ).scalar()
        assert value == "my-post"

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert not COLUMNS & _columns(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert COLUMNS <= _columns(migration_connection)
