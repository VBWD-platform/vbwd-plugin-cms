"""Integration (real PG): the admin permalink-preview endpoint.

``POST /api/v1/admin/cms/posts/permalink-preview`` runs the SAME PermalinkRenderer
+ canonical-URL rule the write path uses (so the fe-admin live preview is DRY),
returns ``{path, url}``, persists nothing, and is admin-gated (401 unauth, 403 for
a non-admin). Config is written through the live ``config_store`` (the only
writer), so the suite runs cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest
from flask import current_app

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType


PREVIEW_URL = "/api/v1/admin/cms/posts/permalink-preview"


@pytest.fixture(autouse=True)
def _post_types():
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
def structured_config(db):
    store = current_app.config_store
    saved = dict(store.get_config("cms") or {})
    store.save_config(
        "cms",
        {
            **saved,
            "posts_permalink_mode": "structured",
            "posts_root": "blog",
            "posts_permalink_include_year": False,
            "posts_permalink_uncategorized_slug": "uncategorized",
            "public_base_url": "https://example.test",
        },
    )
    yield
    store.save_config("cms", saved)


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


def test_preview_requires_auth(client, db):
    assert (
        client.post(PREVIEW_URL, json={"type": "post", "title": "X"}).status_code == 401
    )


def test_preview_rejects_non_admin(client, db, user_headers):
    resp = client.post(
        PREVIEW_URL, json={"type": "post", "title": "X"}, headers=user_headers
    )
    assert resp.status_code == 403


def test_preview_returns_path_and_url(client, db, admin_headers, structured_config):
    suffix = uuid.uuid4().hex[:8]
    term_repo = TermRepository(db.session)
    category = CmsTerm()
    category.term_type = "category"
    category.slug = f"electronics-{suffix}"
    category.name = "Electronics"
    term_repo.save(category)

    resp = client.post(
        PREVIEW_URL,
        json={
            "type": "post",
            "title": "My Post",
            "slug": f"my-post-{suffix}",
            "term_ids": [str(category.id)],
            "primary_term_id": str(category.id),
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    expected = f"blog/electronics-{suffix}/my-post-{suffix}"
    assert body["path"] == expected
    assert body["url"] == f"https://example.test/{expected}"


def test_preview_page_is_verbatim(client, db, admin_headers, structured_config):
    resp = client.post(
        PREVIEW_URL,
        json={"type": "page", "slug": "about/team", "title": "Team"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["path"] == "about/team"
