"""Migration up/down/up for the cms_entity_page link table (real PG, S128).

Additive, non-destructive migration creating ``cms_entity_page`` with a
``UNIQUE(owner_type, owner_id, slot)`` constraint and an ``(owner_type,
owner_id)`` index. Validates: the revision chains off the current cms head,
upgrade creates the table + constraint, downgrade drops it, and a re-upgrade
restores it — against a real connection through alembic's Operations context, in
isolation from the db fixture's ``create_all``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema
only via Alembic; chains within the cms plugin's own migration set; up/down/up
validated); SOLID/DI/DRY; Liskov; no overengineering. Quality guard:
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
        "20260711_1000_cms_entity_page.py",
    )
    spec = importlib.util.spec_from_file_location("cms_entity_page_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()

pytestmark = pytest.mark.no_db_isolation

TABLE = "cms_entity_page"


def _has_table(connection, table: str) -> bool:
    return table in inspect(connection).get_table_names()


@pytest.fixture
def migration_connection(app):
    from vbwd.extensions import db

    connection = db.engine.connect()
    transaction = connection.begin()
    operations = Operations(MigrationContext.configure(connection))
    # create_all() already built the table from the model; drop it so the
    # migration's upgrade runs against a pre-migration shape.
    if _has_table(connection, TABLE):
        operations.drop_table(TABLE)
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


class TestMigrationUpDownUp:
    def test_revision_chains_off_cms_head(self):
        assert migration.revision == "20260711_cms_entity_page"
        assert migration.down_revision == "20260708_cms_post_pinned"
        assert len(migration.revision) <= 32

    def test_upgrade_creates_table(self, migration_connection):
        assert not _has_table(migration_connection, TABLE)
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        assert _has_table(migration_connection, TABLE)
        columns = {
            col["name"] for col in inspect(migration_connection).get_columns(TABLE)
        }
        assert {"owner_type", "owner_id", "slot", "post_id"} <= columns

    def test_unique_owner_slot_constraint_enforced(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
        # Seed a cms_post to satisfy the post_id FK.
        post_id = migration_connection.execute(
            text(
                "INSERT INTO cms_post (id, type, slug, title, content_json, "
                "status, language, robots, seo_excluded, sort_order, "
                "created_at, updated_at, version) VALUES "
                "(gen_random_uuid(), 'entity_page', 'entity-page/dataset/o1/main', "
                "'T', '{}'::json, 'published', 'en', 'index,follow', false, 0, "
                "now(), now(), 0) RETURNING id"
            )
        ).scalar()
        insert = (
            "INSERT INTO cms_entity_page (id, owner_type, owner_id, slot, "
            "post_id, created_at, updated_at, version) VALUES "
            "(gen_random_uuid(), 'dataset', 'o1', 'main', :pid, now(), now(), 0)"
        )
        migration_connection.execute(text(insert), {"pid": post_id})
        with pytest.raises(Exception):
            migration_connection.execute(text(insert), {"pid": post_id})

    def test_downgrade_then_upgrade_round_trips(self, migration_connection):
        context = MigrationContext.configure(migration_connection)
        with Operations.context(context):
            migration.upgrade()
            migration.downgrade()
        assert not _has_table(migration_connection, TABLE)
        with Operations.context(context):
            migration.upgrade()
        assert _has_table(migration_connection, TABLE)
