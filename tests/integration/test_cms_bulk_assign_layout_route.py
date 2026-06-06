"""Integration: POST /admin/cms/posts/bulk/assign-layout (real PG, S54).

Mirrors the existing /posts/bulk/assign-term route: admin-only, sets a real
layout on many posts at once, bad layout -> 400. Posts are seeded through the
service (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services.post_service import PostService
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


def _seed_layout(db):
    layout = CmsLayout(slug=f"lay-{uuid.uuid4().hex[:8]}", name="Lay", areas=[])
    db.session.add(layout)
    db.session.commit()
    return layout


def _seed_post(db, slug):
    return _post_service(db).create_post(
        {"type": "post", "slug": slug, "title": f"T {slug}", "status": "published"}
    )


class TestBulkAssignLayoutRoute:
    def test_assigns_layout_to_selected_posts(self, client, db, admin_headers):
        layout = _seed_layout(db)
        ids = [
            _seed_post(db, f"a-{uuid.uuid4().hex[:8]}")["id"],
            _seed_post(db, f"b-{uuid.uuid4().hex[:8]}")["id"],
        ]
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": ids, "layout_id": str(layout.id)},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"updated": 2}
        for post_id in ids:
            loaded = PostRepository(db.session).find_by_id(post_id)
            assert str(loaded.layout_id) == str(layout.id)

    def test_null_layout_clears_layout_on_selected_posts(
        self, client, db, admin_headers
    ):
        layout = _seed_layout(db)
        post_id = _seed_post(db, f"clr-{uuid.uuid4().hex[:8]}")["id"]
        # First assign a layout, then clear it via a null layout_id.
        client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": [post_id], "layout_id": str(layout.id)},
            headers=admin_headers,
        )
        assert PostRepository(db.session).find_by_id(post_id).layout_id is not None
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": [post_id], "layout_id": None},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"updated": 1}
        assert PostRepository(db.session).find_by_id(post_id).layout_id is None

    def test_bad_layout_returns_400(self, client, db, admin_headers):
        post_id = _seed_post(db, f"c-{uuid.uuid4().hex[:8]}")["id"]
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": [post_id], "layout_id": str(uuid.uuid4())},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_missing_fields_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": "nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": [], "layout_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/assign-layout",
            json={"ids": [], "layout_id": str(uuid.uuid4())},
            headers=user_headers,
        )
        assert resp.status_code == 403
