"""Integration: posts export/import routes (real PG).

The admin export returns the VBWD-standard JSON envelope (as a downloadable
attachment); the import upserts by ``(type, slug)`` and is idempotent; a
round-trip reproduces the post set; the permission gate rejects an
unauthenticated (401) and a non-admin (403) caller; a bad payload returns 400.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL — posts go through the
service); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType


@pytest.fixture(autouse=True)
def _registry():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()


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


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
    )


def _seed_post_with_layout(db, slug):
    layout = CmsLayout(slug=f"lay-{slug}", name="Lay", areas=[])
    db.session.add(layout)
    db.session.commit()
    _post_service(db).create_post(
        {
            "type": "post",
            "slug": slug,
            "title": f"Title {slug}",
            "status": "published",
            "layout_id": str(layout.id),
        }
    )
    return f"lay-{slug}"


class TestExportRoute:
    def test_export_returns_envelope(self, client, db, admin_headers):
        slug = f"hello-{uuid.uuid4().hex[:8]}"
        layout_slug = _seed_post_with_layout(db, slug)
        resp = client.get("/api/v1/admin/cms/posts/export", headers=admin_headers)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.mimetype == "application/json"
        payload = resp.get_json()
        assert payload["entity"] == "cms_post"
        item = next(i for i in payload["items"] if i["slug"] == slug)
        assert item["layout_slug"] == layout_slug
        assert "use_theme_switcher_styles" not in item

    def test_export_type_filter(self, client, db, admin_headers):
        slug = f"only-{uuid.uuid4().hex[:8]}"
        _seed_post_with_layout(db, slug)
        resp = client.get(
            "/api/v1/admin/cms/posts/export?type=page", headers=admin_headers
        )
        assert resp.status_code == 200
        slugs = [i["slug"] for i in resp.get_json()["items"]]
        assert slug not in slugs

    def test_export_requires_auth(self, client, db):
        assert client.get("/api/v1/admin/cms/posts/export").status_code == 401

    def test_export_rejects_non_admin(self, client, db, user_headers):
        resp = client.get("/api/v1/admin/cms/posts/export", headers=user_headers)
        assert resp.status_code == 403


class TestImportRoute:
    def test_import_creates_and_is_idempotent(self, client, db, admin_headers):
        slug = f"imp-{uuid.uuid4().hex[:8]}"
        payload = {
            "version": 1,
            "entity": "cms_post",
            "items": [
                {
                    "type": "post",
                    "slug": slug,
                    "title": "Imported",
                    "status": "published",
                }
            ],
        }
        first = client.post(
            "/api/v1/admin/cms/posts/import", json=payload, headers=admin_headers
        )
        assert first.status_code == 200, first.get_data(as_text=True)
        assert first.get_json() == {"created": 1, "updated": 0}

        second = client.post(
            "/api/v1/admin/cms/posts/import", json=payload, headers=admin_headers
        )
        assert second.get_json() == {"created": 0, "updated": 1}

    def test_round_trip_export_then_import(self, client, db, admin_headers):
        slug = f"rt-{uuid.uuid4().hex[:8]}"
        _seed_post_with_layout(db, slug)
        exported = client.get(
            "/api/v1/admin/cms/posts/export", headers=admin_headers
        ).get_json()
        result = client.post(
            "/api/v1/admin/cms/posts/import", json=exported, headers=admin_headers
        )
        assert result.status_code == 200
        post = PostRepository(db.session).find_by_type_and_slug("post", slug)
        assert post is not None
        assert post.layout_id is not None

    def test_bad_payload_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/import",
            json={"items": [{"type": "ghost", "slug": "x", "title": "X"}]},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/import", json={}, headers=admin_headers
        )
        assert resp.status_code == 400

    def test_import_requires_auth(self, client, db):
        resp = client.post("/api/v1/admin/cms/posts/import", json={"items": []})
        assert resp.status_code == 401

    def test_import_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/import",
            json={"items": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
