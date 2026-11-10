"""Integration (real PG): S154 D7 — the per-type switches reach every PUBLIC signal.

* ``GET /api/v1/cms/posts/<slug>`` and ``GET /api/v1/cms/terms/<type>/<slug>``
  carry ``seo_indexable`` (bool) — the switch of THAT content type (page vs
  post; category vs tag) — so both frontends can emit ``noindex,follow``;
* ``/_seo-render`` forces ``noindex,follow`` on the captured page of a
  switched-off type, and leaves an indexable page byte-for-byte unchanged.

Config through the live ``config_store`` (the shared conftest restores the
cms blob); posts/terms through services; renderer transport patched.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY (one switch resolver, one robots rule); Liskov (the
payloads are otherwise unchanged); clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from flask import current_app

from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import (
    post_type_registry,
    seo_wiring,
    term_type_registry,
)
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services.term_type_registry import TermType

RENDER_URL = "/api/v1/cms/_seo-render"
RENDER_TOKEN = "d7-render-token"
CAPTURED_PAGE_HTML = (
    '<!doctype html><html><head><meta name="robots" content="index,follow">'
    "<title>About</title></head><body><main>About</main></body></html>"
)


@pytest.fixture(autouse=True)
def _registries():
    post_snapshot = list(post_type_registry.list_post_types())
    term_snapshot = list(term_type_registry.list_term_types())
    post_type_registry.clear_post_types()
    for key, hierarchical in (("page", True), ("post", False)):
        post_type_registry.register_post_type(
            PostType(key=key, label=key, routable=True, hierarchical=hierarchical)
        )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    yield
    post_type_registry.clear_post_types()
    term_type_registry.clear_term_types()
    for post_type in post_snapshot:
        post_type_registry.register_post_type(post_type)
    for term_type in term_snapshot:
        term_type_registry.register_term_type(term_type)


def _suffix():
    return uuid.uuid4().hex[:8]


def _create_post(db, post_type, slug):
    created = PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
    ).create_post(
        {"type": post_type, "slug": slug, "title": slug, "status": "published"}
    )
    db.session.commit()
    return created


def _create_category(db, slug):
    TermService(repo=TermRepository(db.session)).create_term(
        {"term_type": "category", "name": slug, "slug": slug}
    )
    db.session.commit()


def _save_cms_config(**values):
    store = current_app.config_store
    store.save_config("cms", {**(store.get_config("cms") or {}), **values})


# ── post / page detail ───────────────────────────────────────────────────────


def test_page_and_post_detail_are_indexable_by_default(client, db):
    page_slug, post_slug = f"d7-page-{_suffix()}", f"d7-post-{_suffix()}"
    _create_post(db, "page", page_slug)
    _create_post(db, "post", post_slug)

    page = client.get(f"/api/v1/cms/posts/{page_slug}").get_json()
    post = client.get(f"/api/v1/cms/posts/{post_slug}?type=post").get_json()

    assert page["seo_indexable"] is True
    assert post["seo_indexable"] is True


def test_detail_follows_the_switch_of_its_own_type(client, db):
    page_slug, post_slug = f"d7-page-{_suffix()}", f"d7-post-{_suffix()}"
    _create_post(db, "page", page_slug)
    _create_post(db, "post", post_slug)
    _save_cms_config(seo_index_pages=False)

    page = client.get(f"/api/v1/cms/posts/{page_slug}").get_json()
    post = client.get(f"/api/v1/cms/posts/{post_slug}?type=post").get_json()

    assert page["seo_indexable"] is False
    assert post["seo_indexable"] is True
    assert page["slug"] == page_slug  # the payload is otherwise unchanged


# ── term archives ────────────────────────────────────────────────────────────


def test_category_archive_is_not_indexable_by_default(client, db):
    slug = f"d7-cat-{_suffix()}"
    _create_category(db, slug)

    body = client.get(f"/api/v1/cms/terms/category/{slug}").get_json()

    assert body["seo_indexable"] is False
    assert body["archive_url"] == f"category/{slug}"


def test_category_archive_follows_its_switch(client, db):
    slug = f"d7-cat-{_suffix()}"
    _create_category(db, slug)
    _save_cms_config(seo_index_categories=True)

    body = client.get(f"/api/v1/cms/terms/category/{slug}").get_json()

    assert body["seo_indexable"] is True


def test_tag_archive_follows_the_tags_switch(app, client, db):
    tag_slug = f"d7-tag-{_suffix()}"
    created = _create_post(db, "post", f"d7-tagged-{_suffix()}")
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "cms_post", uuid.UUID(created["id"]), [tag_slug]
        )

    default_body = client.get(f"/api/v1/cms/terms/tag/{tag_slug}").get_json()
    _save_cms_config(seo_index_tags=True)
    switched_on_body = client.get(f"/api/v1/cms/terms/tag/{tag_slug}").get_json()

    assert default_body["seo_indexable"] is False
    assert switched_on_body["seo_indexable"] is True


# ── /_seo-render ─────────────────────────────────────────────────────────────


def _render(client, path):
    _save_cms_config(
        seo_dynamic_render_enabled=True,
        seo_render_internal_token=RENDER_TOKEN,
        prerender_service_url="http://renderer:3000",
    )
    seo_wiring._render_cache.clear()
    captured = MagicMock(status_code=200, text=CAPTURED_PAGE_HTML)
    with patch(
        "plugins.cms.src.services.seo_full_page_renderer.requests.get",
        return_value=captured,
    ):
        return client.get(
            f"{RENDER_URL}?path={path}", headers={"X-VBWD-Render-Token": RENDER_TOKEN}
        )


def test_seo_render_forces_noindex_follow_for_a_switched_off_page(client, db):
    slug = f"d7-about-{_suffix()}"
    _create_post(db, "page", slug)
    _save_cms_config(seo_index_pages=False)

    response = _render(client, f"/{slug}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('name="robots"') == 1
    assert '<meta name="robots" content="noindex,follow" />' in html
    assert "<main>About</main>" in html


def test_seo_render_keeps_an_indexable_page_unchanged(client, db):
    slug = f"d7-about-{_suffix()}"
    _create_post(db, "page", slug)

    response = _render(client, f"/{slug}")

    assert response.get_data(as_text=True) == CAPTURED_PAGE_HTML


def test_seo_render_forces_noindex_follow_on_a_category_archive_by_default(client, db):
    response = _render(client, f"/category/d7-cat-{_suffix()}")

    assert '<meta name="robots" content="noindex,follow" />' in response.get_data(
        as_text=True
    )
