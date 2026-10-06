"""Integration: no PUBLIC cms response leaks a post's ``preview_token`` (S152 W4).

``CmsPost.to_dict()`` carries ``preview_token`` because fe-admin builds its
shareable preview links from it. The public read endpoints reuse the same
serialization, so anyone reading a published post's JSON kept a token that
still previews the post after it is moved back to draft. The token is stripped
at the public serialization boundary (one helper), while:

  - the admin get / list keep returning it (fe-admin preview links);
  - ``?preview_token=`` on the public single-post GET still previews a draft,
    and a wrong token still answers 403.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL via the ``db`` fixture, cold local + CI); SOLID/
DI/DRY (ONE public-serialization helper used by every public route); Liskov
(public and admin payloads keep the same shape minus the secret); clean code;
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import uuid
from datetime import datetime, timezone

import pytest

from plugins.cms.src.models.cms_post import (
    POST_STATUS_DRAFT,
    POST_STATUS_PUBLISHED,
    CmsPost,
)
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services.term_type_registry import TermType

PREVIEW_TOKEN_KEY = "preview_token"


@pytest.fixture(autouse=True)
def _registries():
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    yield


@pytest.fixture
def admin_headers(client, db):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    body = response.get_json()
    token = body.get("token") or body.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=None,
    )


def _contains_key(payload, key):
    """True when ``key`` appears anywhere in a decoded JSON payload."""
    if isinstance(payload, dict):
        return key in payload or any(
            _contains_key(value, key) for value in payload.values()
        )
    if isinstance(payload, list):
        return any(_contains_key(item, key) for item in payload)
    return False


@pytest.fixture
def seeded(db):
    """A published + a draft post (both with a preview token) in one category."""
    marker = uuid.uuid4().hex[:8]
    post_service = _post_service(db)
    category = TermService(TermRepository(db.session)).create_term(
        {"term_type": "category", "name": "Leak", "slug": f"leak-{marker}"}
    )
    published = post_service.create_post(
        {
            "type": "post",
            "title": f"Leakcheck published {marker}",
            "slug": f"leakcheck-published-{marker}",
            "content_html": f"<p>leakcheck body {marker}</p>",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    draft = post_service.create_post(
        {
            "type": "post",
            "title": f"Leakcheck draft {marker}",
            "slug": f"leakcheck-draft-{marker}",
            "status": POST_STATUS_DRAFT,
        }
    )
    post_service.assign_terms(published["id"], [category["id"]])
    assert published[PREVIEW_TOKEN_KEY] and draft[PREVIEW_TOKEN_KEY]
    return {
        "marker": marker,
        "category_slug": category["slug"],
        "published": published,
        "draft": draft,
    }


def _assert_public_payload_clean(response):
    assert response.status_code == 200, response.get_json()
    assert not _contains_key(response.get_json(), PREVIEW_TOKEN_KEY)


# ── public endpoints never carry the token ───────────────────────────────────


def test_public_get_post_omits_preview_token(app, db, client, seeded):
    slug = seeded["published"]["slug"]
    _assert_public_payload_clean(client.get(f"/api/v1/cms/posts/{slug}?type=post"))


def test_public_list_posts_omits_preview_token(app, db, client, seeded):
    response = client.get("/api/v1/cms/posts?type=post&per_page=100")
    _assert_public_payload_clean(response)
    assert response.get_json()["items"], "list must return items to be meaningful"


def test_public_list_posts_by_term_omits_preview_token(app, db, client, seeded):
    response = client.get(
        "/api/v1/cms/posts?type=post&term_type=category"
        f"&term_slug={seeded['category_slug']}"
    )
    _assert_public_payload_clean(response)
    assert [item["id"] for item in response.get_json()["items"]] == [
        seeded["published"]["id"]
    ]


def test_public_search_omits_preview_token(app, db, client, seeded):
    response = client.get(f"/api/v1/cms/search?q=leakcheck {seeded['marker']}")
    _assert_public_payload_clean(response)
    assert response.get_json()["items"], "search must return items to be meaningful"


def test_public_archive_omits_preview_token(app, db, client):
    prefix = f"leakarchive-{uuid.uuid4().hex[:8]}"
    post = CmsPost()
    post.type = "post"
    post.slug = f"{prefix}/2026/item"
    post.title = "item"
    post.content_json = {}
    post.status = POST_STATUS_PUBLISHED
    post.published_at = datetime.now(timezone.utc)
    post.preview_token = uuid.uuid4().hex
    db.session.add(post)
    db.session.commit()

    response = client.get(f"/api/v1/cms/archive/{prefix}")
    _assert_public_payload_clean(response)
    assert response.get_json()["total"] == 1


# ── the preview flow keeps working ───────────────────────────────────────────


def test_preview_with_matching_token_returns_draft_without_echoing_it(
    app, db, client, seeded
):
    draft = seeded["draft"]
    response = client.get(
        f"/api/v1/cms/posts/{draft['slug']}?type=post"
        f"&preview_token={draft[PREVIEW_TOKEN_KEY]}"
    )
    _assert_public_payload_clean(response)
    assert response.get_json()["id"] == draft["id"]


def test_preview_with_wrong_token_is_forbidden(app, db, client, seeded):
    draft = seeded["draft"]
    response = client.get(
        f"/api/v1/cms/posts/{draft['slug']}?type=post&preview_token=not-the-token"
    )
    assert response.status_code == 403


def test_draft_without_token_stays_hidden(app, db, client, seeded):
    response = client.get(f"/api/v1/cms/posts/{seeded['draft']['slug']}?type=post")
    assert response.status_code == 404


# ── admin endpoints keep the token (fe-admin preview links) ──────────────────


def test_admin_get_post_keeps_preview_token(app, db, client, seeded, admin_headers):
    draft = seeded["draft"]
    response = client.get(
        f"/api/v1/admin/cms/posts/{draft['id']}", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.get_json()[PREVIEW_TOKEN_KEY] == draft[PREVIEW_TOKEN_KEY]


def test_admin_list_posts_keeps_preview_token(app, db, client, seeded, admin_headers):
    response = client.get(
        f"/api/v1/admin/cms/posts?type=post&search={seeded['marker']}&per_page=100",
        headers=admin_headers,
    )
    assert response.status_code == 200
    tokens_by_id = {
        item["id"]: item.get(PREVIEW_TOKEN_KEY) for item in response.get_json()["items"]
    }
    assert tokens_by_id[seeded["draft"]["id"]] == seeded["draft"][PREVIEW_TOKEN_KEY]
