"""Integration: POST /admin/cms/posts/bulk/unassign-category (real PG).

Extends the S54 bulk-assign family with a bulk-CLEAR for categories: removing
all ``category``-type terms from the selected posts while keeping tags (and any
other term type) untouched. Admin-only. Posts and terms are seeded through the
service/repository layer (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_term import CmsTerm
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


def _seed_term(db, term_type):
    term = CmsTerm()
    term.term_type = term_type
    term.slug = f"{term_type}-{uuid.uuid4().hex[:8]}"
    term.name = term.slug
    return TermRepository(db.session).save(term)


def _seed_post(db, slug):
    return _post_service(db).create_post(
        {"type": "post", "slug": slug, "title": f"T {slug}", "status": "published"}
    )


class TestBulkUnassignCategoryRoute:
    def test_removes_category_keeps_tag(self, client, db, admin_headers):
        category = _seed_term(db, "category")
        tag = _seed_term(db, "tag")
        post_id = _seed_post(db, f"a-{uuid.uuid4().hex[:8]}")["id"]
        _post_service(db).assign_terms(post_id, [str(category.id), str(tag.id)])

        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/unassign-category",
            json={"ids": [post_id]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"updated": 1}

        remaining = [
            str(link.term_id)
            for link in PostTermRepository(db.session).find_by_post(post_id)
        ]
        assert remaining == [str(tag.id)]

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/unassign-category",
            json={"ids": "nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/unassign-category",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/unassign-category",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
