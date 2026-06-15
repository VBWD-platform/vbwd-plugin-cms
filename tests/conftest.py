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

    # Build the schema once per process (create_all, checkfirst — never drops,
    # so it cannot wipe data) and commit baseline reference rows once. Each test
    # then isolates itself via a rolled-back transaction (no TRUNCATE, no DROP) —
    # see vbwd/testing/integration_db.py.
    with app.app_context():
        from vbwd.extensions import db as _db
        from vbwd.testing.integration_db import ensure_schema_and_baseline

        # Import the cms model the core create_app() does not auto-register so
        # its table is part of the one-time create_all().
        import plugins.cms.src.models.cms_page_widget  # noqa: F401

        ensure_schema_and_baseline(_db)

    yield app

    with app.app_context():
        from vbwd.extensions import db as _db

        _db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """Isolate each test in a rolled-back transaction (self-cleaning, no wipe).

    The schema + baseline RBAC rows are built once in the ``app`` fixture; each
    test runs inside a transaction that is rolled back at teardown, so nothing it
    writes persists. The admin user the integration tests log in with is seeded
    inside that transaction so the route paths see it on the same connection; it
    rolls back with the rest of the test's writes. See
    vbwd/testing/integration_db.py.
    """
    from vbwd.extensions import db

    with app.app_context():
        from vbwd.testing.integration_db import rollback_isolation

        with rollback_isolation(db):
            # Seed admin user so integration tests can log in.
            os.environ["TEST_DATA_SEED"] = "true"
            from vbwd.testing.test_data_seeder import TestDataSeeder

            TestDataSeeder(db.session).seed()
            yield db
