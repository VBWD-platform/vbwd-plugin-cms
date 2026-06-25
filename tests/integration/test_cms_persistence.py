"""Integration: the public/admin category endpoints serve the unified taxonomy.

The legacy ``cms_page`` / ``cms_category`` subsystem was retired (S105). The two
remaining category endpoints (``GET /api/v1/cms/categories`` and
``GET /api/v1/admin/cms/categories``) are now backed by the unified ``cms_term``
taxonomy — this test proves a seeded ``cms_term(term_type=category)`` surfaces
through both, and that the removed legacy page/category write routes are gone.

Unified post/category persistence + multi-segment slug routing are covered by
``test_cms_unified_persistence.py`` and ``test_cms_post_*`` — not re-asserted here.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG,
cold local + CI); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services.term_type_registry import TermType
from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE


@pytest.fixture(autouse=True)
def _category_term_type():
    if not term_type_registry.is_registered(CATEGORY_TERM_TYPE):
        term_type_registry.register_term_type(
            TermType(key=CATEGORY_TERM_TYPE, label="Category", hierarchical=True)
        )
    yield


@pytest.fixture(autouse=True)
def admin_token(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    if resp.status_code != 200:
        pytest.skip("Admin user not available in test DB")
    data = resp.get_json()
    return data.get("token") or data.get("access_token")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _seed_category(db) -> str:
    slug = f"news-{uuid.uuid4().hex[:8]}"
    TermService(TermRepository(db.session)).create_term(
        {"term_type": CATEGORY_TERM_TYPE, "name": "News", "slug": slug}
    )
    db.session.commit()
    return slug


class TestCategoriesBackedByCmsTerm:
    def test_public_categories_returns_cms_term_categories(self, client, db):
        slug = _seed_category(db)
        resp = client.get("/api/v1/cms/categories")
        assert resp.status_code == 200
        slugs = [c["slug"] for c in resp.get_json()]
        assert slug in slugs

    def test_admin_categories_returns_cms_term_categories(
        self, client, db, auth_headers
    ):
        slug = _seed_category(db)
        resp = client.get("/api/v1/admin/cms/categories", headers=auth_headers)
        assert resp.status_code == 200
        slugs = [c["slug"] for c in resp.get_json()]
        assert slug in slugs


class TestLegacyRoutesRetired:
    """The legacy page + category-write routes are gone (S105)."""

    def test_legacy_single_page_route_removed(self, client):
        assert client.get("/api/v1/cms/pages/anything").status_code == 404

    def test_legacy_page_list_route_removed(self, client):
        assert client.get("/api/v1/cms/pages").status_code == 404

    def test_legacy_admin_page_list_route_removed(self, client, auth_headers):
        resp = client.get("/api/v1/admin/cms/pages", headers=auth_headers)
        assert resp.status_code == 404

    def test_legacy_admin_category_create_route_removed(self, client, auth_headers):
        resp = client.post(
            "/api/v1/admin/cms/categories",
            json={"name": "X", "slug": "x"},
            headers=auth_headers,
        )
        assert resp.status_code in (404, 405)
