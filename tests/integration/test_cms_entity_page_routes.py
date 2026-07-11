"""Integration: generic entity-page admin + public routes (real PG, S128).

Drives the reusable capability end-to-end:
  - admin GET scaffolds an unlinked owner (empty content + all 10 SEO keys);
  - admin PUT persists content + custom CSS + every SEO field + a content block,
    resolve-or-creating the ``entity_page`` post + link; a reload reads it back;
  - the owner type's ``authorize`` gates access — unknown type → 404,
    unauthorized → 403 (Liskov: never a 500);
  - the public GET returns the published projection (404 when unlinked);
  - an ``entity_page`` post is ABSENT from the CMS Pages admin list
    (``?type=page``) — it never appears as a standalone CMS page.

All data flows through the routes/services (no raw SQL). Restated engineering
requirements: TDD-first; DevOps-first (cold local + CI via the shared ``db``
fixture); SOLID (OCP owner registry, SRP link table); DI; DRY; Liskov; clean
code; no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import uuid

import pytest

from plugins.cms.src.services import post_type_registry, entity_page_owner_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.entity_page_owner_registry import ContentOwnerType


OWNER_TYPE = "test_owner"
LOCKED_OWNER_TYPE = "locked_owner"


@pytest.fixture(autouse=True)
def _registry():
    """Register the built-in post types + the test owner types.

    Self-sufficient regardless of collection order: sibling suites clear the
    post-type registry, so we (idempotently) re-register page/post/entity_page
    and the two owner types this suite drives.
    """
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    post_type_registry.register_post_type(
        PostType(
            key="entity_page",
            label="Entity Page",
            routable=False,
            hierarchical=False,
        )
    )
    entity_page_owner_registry.clear_content_owner_types()
    entity_page_owner_registry.register_content_owner_type(
        ContentOwnerType(
            key=OWNER_TYPE, label="Test Owner", authorize=lambda user, owner_id: True
        )
    )
    entity_page_owner_registry.register_content_owner_type(
        ContentOwnerType(
            key=LOCKED_OWNER_TYPE,
            label="Locked",
            authorize=lambda user, owner_id: False,
        )
    )
    yield
    entity_page_owner_registry.clear_content_owner_types()


@pytest.fixture
def admin_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _owner_id() -> str:
    return uuid.uuid4().hex


def _full_seo_body() -> dict:
    return {
        "content_html": "<p>Authored body</p>",
        "content_json": {"blocks": ["x"]},
        "source_css": ".entity-page{color:blue}",
        "content_blocks": [
            {"area_name": "extra", "content_html": "<p>an extra block</p>"}
        ],
        "seo": {
            "meta_title": "Meta Title",
            "meta_description": "Meta Description",
            "meta_keywords": "k1,k2",
            "og_title": "OG Title",
            "og_description": "OG Description",
            "og_image_url": "https://example.com/og.png",
            "canonical_url": "https://example.com/canon",
            "robots": "noindex,nofollow",
            "schema_json": {"@type": "Dataset"},
            "seo_excluded": True,
        },
    }


class TestAdminEntityPage:
    def test_get_scaffold_when_unlinked(self, client, db, admin_headers):
        owner_id = _owner_id()
        resp = client.get(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["content_html"] == ""
        assert body["source_css"] == ""
        assert body["content_blocks"] == []
        seo = body["seo"]
        for field in (
            "meta_title",
            "meta_description",
            "meta_keywords",
            "og_title",
            "og_description",
            "og_image_url",
            "canonical_url",
            "robots",
            "schema_json",
            "seo_excluded",
        ):
            assert field in seo
        assert seo["robots"] == "index,follow"
        assert seo["seo_excluded"] is False

    def test_put_persists_everything_then_reload(self, client, db, admin_headers):
        owner_id = _owner_id()
        put = client.put(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
            json=_full_seo_body(),
        )
        assert put.status_code == 200
        saved = put.get_json()
        assert saved["content_html"] == "<p>Authored body</p>"
        assert saved["source_css"] == ".entity-page{color:blue}"
        assert len(saved["content_blocks"]) == 1
        assert saved["content_blocks"][0]["area_name"] == "extra"
        assert saved["seo"]["meta_title"] == "Meta Title"
        assert saved["seo"]["robots"] == "noindex,nofollow"
        assert saved["seo"]["seo_excluded"] is True
        assert saved["seo"]["schema_json"] == {"@type": "Dataset"}

        # Reload via GET reads the persisted values back.
        got = client.get(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
        )
        assert got.status_code == 200
        reloaded = got.get_json()
        assert reloaded["content_html"] == "<p>Authored body</p>"
        assert reloaded["source_css"] == ".entity-page{color:blue}"
        assert reloaded["content_blocks"][0]["content_html"] == "<p>an extra block</p>"
        assert reloaded["seo"]["canonical_url"] == "https://example.com/canon"

    def test_put_is_idempotent_updates_same_page(self, client, db, admin_headers):
        owner_id = _owner_id()
        first = client.put(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
            json={"content_html": "<p>one</p>"},
        )
        second = client.put(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
            json={"content_html": "<p>two</p>"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.get_json()["post_id"] == second.get_json()["post_id"]
        assert second.get_json()["content_html"] == "<p>two</p>"

    def test_unknown_owner_type_404(self, client, db, admin_headers):
        resp = client.get(
            f"/api/v1/admin/cms/entity-pages/no_such_type/{_owner_id()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_unauthorized_owner_403(self, client, db, admin_headers):
        resp = client.get(
            f"/api/v1/admin/cms/entity-pages/{LOCKED_OWNER_TYPE}/{_owner_id()}",
            headers=admin_headers,
        )
        assert resp.status_code == 403

    def test_put_unauthorized_owner_403(self, client, db, admin_headers):
        resp = client.put(
            f"/api/v1/admin/cms/entity-pages/{LOCKED_OWNER_TYPE}/{_owner_id()}",
            headers=admin_headers,
            json={"content_html": "<p>x</p>"},
        )
        assert resp.status_code == 403

    def test_requires_auth(self, client, db):
        resp = client.get(f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{_owner_id()}")
        assert resp.status_code in (401, 403)


class TestPublicEntityPage:
    def test_public_get_404_when_unlinked(self, client, db):
        resp = client.get(f"/api/v1/cms/entity-pages/{OWNER_TYPE}/{_owner_id()}")
        assert resp.status_code == 404

    def test_public_get_returns_published_projection(self, client, db, admin_headers):
        owner_id = _owner_id()
        client.put(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
            json=_full_seo_body(),
        )
        resp = client.get(f"/api/v1/cms/entity-pages/{OWNER_TYPE}/{owner_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["content_html"] == "<p>Authored body</p>"
        assert body["source_css"] == ".entity-page{color:blue}"
        assert body["seo"]["meta_title"] == "Meta Title"
        assert body["content_blocks"][0]["area_name"] == "extra"


class TestEntityPageNotAPage:
    def test_entity_page_absent_from_admin_pages_list(self, client, db, admin_headers):
        owner_id = _owner_id()
        put = client.put(
            f"/api/v1/admin/cms/entity-pages/{OWNER_TYPE}/{owner_id}",
            headers=admin_headers,
            json={"content_html": "<p>hidden from pages</p>"},
        )
        entity_post_id = put.get_json()["post_id"]

        pages = client.get(
            "/api/v1/admin/cms/posts?type=page&per_page=100", headers=admin_headers
        )
        assert pages.status_code == 200
        page_ids = {item["id"] for item in pages.get_json()["items"]}
        assert entity_post_id not in page_ids

        posts = client.get(
            "/api/v1/admin/cms/posts?type=post&per_page=100", headers=admin_headers
        )
        post_ids = {item["id"] for item in posts.get_json()["items"]}
        assert entity_post_id not in post_ids
