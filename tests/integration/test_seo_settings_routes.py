"""Integration (real PG): S56.0 SEO admin settings + robots/sitemap effects.

Proves the editable robots.txt + configurable sitemap end to end against the
booted app (cms enabled, so the sitemap provider + root routes are live):

  * PUT ``/admin/cms/seo/settings`` persists, then GET returns the same values;
  * the MERGE does not clobber other cms config keys (``seo_prerender_enabled``);
  * ``/robots.txt`` serves a saved custom body verbatim;
  * ``/sitemap.xml`` omits an excluded-slug post, an exclude-term post, and all
    pages when ``sitemap_include_pages=false``;
  * ``sitemap_include_terms`` restricts the sitemap to posts carrying a match.

Posts + terms are seeded through the services/repositories (no raw SQL); the
config is written through the live ``config_store`` (the only writer), so the
suite runs cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov (a missing config falls back to the no-filter default); clean
code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest
from flask import current_app

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType


SETTINGS_URL = "/api/v1/admin/cms/seo/settings"


@pytest.fixture(autouse=True)
def _registries():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    yield
    post_type_registry.clear_post_types()
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


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
    )


def _term_service(db):
    return TermService(repo=TermRepository(db.session))


def _create_post(db, post_type, slug, term_ids=None):
    service = _post_service(db)
    created = service.create_post(
        {
            "type": post_type,
            "slug": slug,
            "title": f"Title {slug}",
            "canonical_url": f"https://x/{slug}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    if term_ids:
        service.assign_terms(created["id"], term_ids)
    db.session.commit()
    return created


def _sitemap_locs(client):
    body = client.get("/sitemap.xml").get_data(as_text=True)
    return body


# ── settings persistence + merge ─────────────────────────────────────────────


def test_put_then_get_returns_saved_settings(client, db, admin_headers):
    payload = {
        "robots_txt": "User-agent: *\nDisallow: /private\n",
        "sitemap_include_pages": False,
        "sitemap_excluded_slugs": ["secret"],
        "sitemap_include_terms": ["featured"],
        "sitemap_exclude_terms": ["hidden"],
    }
    put = client.put(SETTINGS_URL, json=payload, headers=admin_headers)
    assert put.status_code == 200

    got = client.get(SETTINGS_URL, headers=admin_headers).get_json()
    assert got["robots_txt"] == payload["robots_txt"]
    assert got["sitemap_include_pages"] is False
    assert got["sitemap_excluded_slugs"] == ["secret"]
    assert got["sitemap_include_terms"] == ["featured"]
    assert got["sitemap_exclude_terms"] == ["hidden"]


def test_put_merges_without_clobbering_other_keys(client, db, admin_headers):
    store = current_app.config_store
    config = store.get_config("cms") or {}
    config["seo_prerender_enabled"] = True
    config["uploads_base_path"] = "/app/uploads"
    store.save_config("cms", config)

    client.put(SETTINGS_URL, json={"robots_txt": "X"}, headers=admin_headers)

    after = store.get_config("cms")
    assert after["robots_txt"] == "X"
    assert after["seo_prerender_enabled"] is True
    assert after["uploads_base_path"] == "/app/uploads"


def test_global_head_html_persists_and_merges(client, db, admin_headers):
    """The new ``global_head_html`` raw-text setting persists via GET/PUT and
    merges into the cms config without clobbering existing SEO keys."""
    store = current_app.config_store
    config = store.get_config("cms") or {}
    config["robots_txt"] = "User-agent: *\nDisallow: /keep\n"
    store.save_config("cms", config)

    snippet = '<meta name="msvalidate.01" content="TESTKEY" />'
    put = client.put(
        SETTINGS_URL, json={"global_head_html": snippet}, headers=admin_headers
    )
    assert put.status_code == 200
    assert put.get_json()["global_head_html"] == snippet

    got = client.get(SETTINGS_URL, headers=admin_headers).get_json()
    assert got["global_head_html"] == snippet
    # The merge preserved the previously-saved robots_txt.
    assert got["robots_txt"] == "User-agent: *\nDisallow: /keep\n"


def test_put_ignores_unknown_keys_and_coerces_types(client, db, admin_headers):
    payload = {
        "robots_txt": 123,
        "sitemap_excluded_slugs": ["a", "", "  b  ", 5],
        "totally_unknown": "nope",
    }
    client.put(SETTINGS_URL, json=payload, headers=admin_headers)
    after = current_app.config_store.get_config("cms")
    assert after["robots_txt"] == "123"
    assert after["sitemap_excluded_slugs"] == ["a", "b"]
    assert "totally_unknown" not in after


def test_settings_requires_admin(client, db):
    assert client.get(SETTINGS_URL).status_code == 401


# ── robots.txt reflects saved custom body ────────────────────────────────────


def test_robots_serves_saved_custom_body(client, db, admin_headers):
    custom = "User-agent: *\nDisallow: /everything\n"
    client.put(SETTINGS_URL, json={"robots_txt": custom}, headers=admin_headers)
    body = client.get("/robots.txt").get_data(as_text=True)
    assert body == custom


# ── sitemap filtering ────────────────────────────────────────────────────────


def test_sitemap_omits_excluded_slug(client, db, admin_headers):
    keep = f"keep-{uuid.uuid4().hex[:6]}"
    drop = f"drop-{uuid.uuid4().hex[:6]}"
    _create_post(db, "post", keep)
    _create_post(db, "post", drop)
    client.put(
        SETTINGS_URL, json={"sitemap_excluded_slugs": [drop]}, headers=admin_headers
    )
    body = _sitemap_locs(client)
    assert f"https://x/{keep}" in body
    assert f"https://x/{drop}" not in body


def test_sitemap_omits_pages_when_include_pages_false(client, db, admin_headers):
    page = f"page-{uuid.uuid4().hex[:6]}"
    post = f"post-{uuid.uuid4().hex[:6]}"
    _create_post(db, "page", page)
    _create_post(db, "post", post)
    client.put(
        SETTINGS_URL, json={"sitemap_include_pages": False}, headers=admin_headers
    )
    body = _sitemap_locs(client)
    assert f"https://x/{post}" in body
    assert f"https://x/{page}" not in body


def test_sitemap_omits_exclude_term_post(client, db, admin_headers):
    term_slug = f"hidden-{uuid.uuid4().hex[:6]}"
    term = _term_service(db).create_term(
        {"term_type": "category", "name": "Hidden", "slug": term_slug}
    )
    keep = f"keep-{uuid.uuid4().hex[:6]}"
    drop = f"drop-{uuid.uuid4().hex[:6]}"
    _create_post(db, "post", keep)
    _create_post(db, "post", drop, term_ids=[term["id"]])
    client.put(
        SETTINGS_URL, json={"sitemap_exclude_terms": [term_slug]}, headers=admin_headers
    )
    body = _sitemap_locs(client)
    assert f"https://x/{keep}" in body
    assert f"https://x/{drop}" not in body


def test_sitemap_include_terms_restricts_to_matching(client, db, admin_headers):
    term_slug = f"feat-{uuid.uuid4().hex[:6]}"
    term = _term_service(db).create_term(
        {"term_type": "category", "name": "Featured", "slug": term_slug}
    )
    matching = f"match-{uuid.uuid4().hex[:6]}"
    other = f"other-{uuid.uuid4().hex[:6]}"
    _create_post(db, "post", matching, term_ids=[term["id"]])
    _create_post(db, "post", other)
    client.put(
        SETTINGS_URL, json={"sitemap_include_terms": [term_slug]}, headers=admin_headers
    )
    body = _sitemap_locs(client)
    assert f"https://x/{matching}" in body
    assert f"https://x/{other}" not in body
