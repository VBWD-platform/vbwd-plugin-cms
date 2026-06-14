"""Test fixtures for CMS plugin tests."""
import pytest
import os
import sys

# Ensure project root is on the path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
)

os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"


def _test_db_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_test"


def _ensure_test_db(url: str) -> None:
    from sqlalchemy import create_engine, text

    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app():
    from vbwd.app import create_app

    url = _test_db_url()
    _ensure_test_db(url)
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URL": "memory://",
    }
    app = create_app(test_config)
    from vbwd.extensions import limiter

    limiter.reset()

    # Build the full schema exactly ONCE for the whole session. A per-test
    # create_all()/drop_all() (the old approach) churns DDL on db.metadata,
    # whose table set differs per test file (each file imports a different
    # model subset). That stranded ENUM types (duplicate "userstatus"),
    # dropped shared tables another file needs ("vbwd_user does not exist"),
    # and deadlocked under the concurrent DDL — so the whole suite could not
    # run together. We instead reset the public schema once (clearing any
    # table or ENUM left by a prior crashed run) and create_all() once; each
    # test then isolates by TRUNCATE-ing data, not by dropping the schema.
    with app.app_context():
        from sqlalchemy import text

        from vbwd.extensions import db as _db

        # Import the cms model the core create_app() does not auto-register so
        # its table is part of the one-time create_all().
        import plugins.cms.src.models.cms_page_widget  # noqa: F401

        # Reset the schema and create every table on the SAME fresh connection,
        # so create_all()'s checkfirst reflection sees the just-cleared catalog
        # (a separate pooled connection can carry a pre-DROP snapshot and then
        # create_all() skips/duplicates tables). Close any session first so no
        # idle transaction holds a lock against the DROP.
        _db.session.remove()
        with _db.engine.connect() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.commit()
            _db.metadata.create_all(bind=connection)
            connection.commit()

    yield app

    with app.app_context():
        from vbwd.extensions import db as _db

        _db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from sqlalchemy import inspect, text

    from vbwd.extensions import db

    with app.app_context():
        # Isolate each test by clearing data (not schema). Reflect the tables
        # that actually exist in the DB so we never depend on db.metadata's
        # per-file subset, then truncate them all in one statement. Truncating
        # on SETUP (not teardown) is robust against a prior test that left
        # rows.
        #
        # Run the TRUNCATE on its OWN short-lived connection (engine.begin()),
        # not on db.session. db.session can carry an open transaction from a
        # prior test's seed/queries; truncating through it left two concurrent
        # transactions racing for AccessExclusiveLock on the same ~100 tables
        # and PostgreSQL aborted one with "deadlock detected". A dedicated
        # autocommit-scoped connection takes and releases all the table locks
        # atomically, so nothing else can interleave. Drop the scoped session
        # first so it holds no locks against the TRUNCATE.
        db.session.remove()
        table_names = inspect(db.engine).get_table_names(schema="public")
        if table_names:
            quoted = ", ".join(f'public."{name}"' for name in table_names)
            with db.engine.begin() as connection:
                connection.execute(
                    text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
                )
                # Re-seed the canonical RBAC role rows the TRUNCATE wiped, so
                # TestDataSeeder's user (role=USER) does not violate the
                # vbwd_user_role FK. Mirrors the subscription conftest; through
                # the model, never raw DDL.
                if "vbwd_user_role" in table_names:
                    from sqlalchemy import insert as _insert
                    from vbwd.models.user_role import (
                        RoleDefinition as _RoleDefinition,
                        canonical_role_rows as _canonical_role_rows,
                    )

                    connection.execute(
                        _insert(_RoleDefinition.__table__), _canonical_role_rows()
                    )

        # Seed admin user so integration tests can log in.
        os.environ["TEST_DATA_SEED"] = "true"
        from vbwd.testing.test_data_seeder import TestDataSeeder

        TestDataSeeder(db.session).seed()
        yield db
        db.session.remove()
