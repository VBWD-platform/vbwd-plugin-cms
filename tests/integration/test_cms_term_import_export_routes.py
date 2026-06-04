"""Integration: taxonomy export/import routes (real PG).

The admin export returns the VBWD-standard JSON envelope; the import upserts by
``(term_type, slug)`` and is idempotent; a round-trip reproduces the term set;
the permission gate rejects an unauthenticated (401) and a non-admin (403)
caller; a bad payload returns 400.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL — terms go through the
service); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services.term_type_registry import TermType


@pytest.fixture(autouse=True)
def _registries():
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
    )
    yield
    term_type_registry.clear_term_types()


@pytest.fixture
def admin_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _seed_two_categories(db):
    service = TermService(TermRepository(db.session))
    parent = service.create_term(
        {"term_type": "category", "slug": "world", "name": "World"}
    )
    service.create_term(
        {
            "term_type": "category",
            "slug": "europe",
            "name": "Europe",
            "parent_id": parent["id"],
        }
    )


class TestExportRoute:
    def test_export_returns_envelope(self, client, db, admin_headers):
        _seed_two_categories(db)
        resp = client.get("/api/v1/admin/cms/terms/export", headers=admin_headers)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.mimetype == "application/json"
        payload = resp.get_json()
        assert payload["version"] == 1
        assert payload["entity"] == "cms_term"
        slugs = {item["slug"]: item for item in payload["items"]}
        assert slugs["europe"]["parent_slug"] == "world"

    def test_export_type_filter(self, client, db, admin_headers):
        service = TermService(TermRepository(db.session))
        service.create_term({"term_type": "tag", "slug": "hot", "name": "Hot"})
        _seed_two_categories(db)
        resp = client.get(
            "/api/v1/admin/cms/terms/export?type=tag", headers=admin_headers
        )
        assert resp.status_code == 200
        slugs = [item["slug"] for item in resp.get_json()["items"]]
        assert slugs == ["hot"]

    def test_export_requires_auth(self, client, db):
        assert client.get("/api/v1/admin/cms/terms/export").status_code == 401

    def test_export_rejects_non_admin(self, client, db, user_headers):
        resp = client.get("/api/v1/admin/cms/terms/export", headers=user_headers)
        assert resp.status_code == 403


class TestImportRoute:
    def test_import_creates_and_is_idempotent(self, client, db, admin_headers):
        payload = {
            "version": 1,
            "entity": "cms_term",
            "items": [
                {"term_type": "category", "slug": "world", "name": "World"},
                {
                    "term_type": "category",
                    "slug": "europe",
                    "name": "Europe",
                    "parent_slug": "world",
                },
            ],
        }
        first = client.post(
            "/api/v1/admin/cms/terms/import", json=payload, headers=admin_headers
        )
        assert first.status_code == 200, first.get_data(as_text=True)
        assert first.get_json() == {"created": 2, "updated": 0}

        second = client.post(
            "/api/v1/admin/cms/terms/import", json=payload, headers=admin_headers
        )
        assert second.get_json() == {"created": 0, "updated": 2}

    def test_round_trip_export_then_import(self, client, db, admin_headers):
        _seed_two_categories(db)
        exported = client.get(
            "/api/v1/admin/cms/terms/export", headers=admin_headers
        ).get_json()

        result = client.post(
            "/api/v1/admin/cms/terms/import", json=exported, headers=admin_headers
        )
        assert result.status_code == 200
        # The round-trip matched both existing terms — no new rows.
        assert result.get_json() == {"created": 0, "updated": 2}

    def test_bad_payload_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/terms/import",
            json={"items": [{"term_type": "series", "name": "Saga"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/terms/import", json={}, headers=admin_headers
        )
        assert resp.status_code == 400

    def test_import_requires_auth(self, client, db):
        resp = client.post("/api/v1/admin/cms/terms/import", json={"items": []})
        assert resp.status_code == 401

    def test_import_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/terms/import",
            json={"items": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
