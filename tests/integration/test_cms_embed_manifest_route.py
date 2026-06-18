"""S91 Slice 1 — GET /api/v1/cms/embed-manifest (mobile fail-loud validation probe).

The mobile app calls this once on entry before pointing a WebView at the host's
CMS archive, so a mis-configured device (unregistered post-type or unknown
category slug) shows a clear native error state instead of a blank browser.

Contract (sprint §3 / §Slice 1):
  - 200 {ok, type, category:{slug,name}, post_count, archive_url} when both the
    post-type is registered and the category slug resolves.
  - 404 {error} with distinct messages for an unregistered type vs an unknown
    category slug.
  - 400 {error} when ``type`` or ``category`` is missing (mirrors the existing
    public_list_terms 400 style).
  - ``archive_url`` is the RELATIVE embed path ``/cms/embed/<type>/<category>``;
    the backend does not know the web origin (the device derives it from
    ``api_base_url``).

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG
via the ``db`` fixture, clean cold start); SOLID/DI/DRY (reuses the post-type
registry + TermService + PostService count — no new query path); Liskov; clean
code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType


@pytest.fixture(autouse=True)
def _post_type_registry_baseline():
    """Deterministic post-type registry: ``page`` + ``post`` registered.

    The registry is process-global and sibling suites mutate it, so this suite
    sets its own baseline (mirroring the plugin's on_enable) instead of relying
    on collection order, then restores it on teardown.
    """
    snapshot = list(post_type_registry.list_post_types())
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()
    for post_type in snapshot:
        post_type_registry.register_post_type(post_type)


def _make_published_post(db, slug, post_type="post"):
    from plugins.cms.src.models.cms_post import CmsPost

    post = CmsPost()
    post.type = post_type
    post.slug = slug
    post.title = slug
    post.content_json = {}
    post.status = "published"
    db.session.add(post)
    db.session.commit()
    return post


def _make_category(db, name, slug):
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.services.term_service import TermService

    term_service = TermService(TermRepository(db.session))
    return term_service.create_term(
        {"term_type": "category", "name": name, "slug": slug}
    )


def test_valid_type_and_category_returns_ok_with_count_and_archive_url(app, db, client):
    suffix = uuid.uuid4().hex[:8]
    category_slug = f"news-{suffix}"
    category = _make_category(db, "News", category_slug)

    from plugins.cms.src.repositories.post_term_repository import PostTermRepository

    post = _make_published_post(db, f"story-{suffix}", post_type="post")
    PostTermRepository(db.session).replace_for_post(str(post.id), [category["id"]])

    response = client.get(
        f"/api/v1/cms/embed-manifest?type=post&category={category_slug}"
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["type"] == "post"
    assert body["category"] == {"slug": category_slug, "name": "News"}
    assert body["post_count"] == 1
    assert body["archive_url"] == f"/cms/embed/post/{category_slug}"


def test_unregistered_type_returns_404(app, db, client):
    suffix = uuid.uuid4().hex[:8]
    category_slug = f"news-{suffix}"
    _make_category(db, "News", category_slug)

    response = client.get(
        f"/api/v1/cms/embed-manifest?type=nonsense&category={category_slug}"
    )
    body = response.get_json()

    assert response.status_code == 404
    assert "nonsense" in body["error"]
    assert "not registered" in body["error"]


def test_unknown_category_slug_returns_404(app, db, client):
    response = client.get(
        "/api/v1/cms/embed-manifest?type=post&category=does-not-exist"
    )
    body = response.get_json()

    assert response.status_code == 404
    assert "does-not-exist" in body["error"]
    assert "not found" in body["error"]


def test_missing_type_param_returns_400(app, db, client):
    response = client.get("/api/v1/cms/embed-manifest?category=news")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_missing_category_param_returns_400(app, db, client):
    response = client.get("/api/v1/cms/embed-manifest?type=post")

    assert response.status_code == 400
    assert "error" in response.get_json()
