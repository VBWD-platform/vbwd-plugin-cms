"""Integration (real PG): S154 P2 — cms indexable-type switches drive the sitemap.

* ``seo_index_pages`` / ``seo_index_posts`` narrow the ``cms`` provider in SQL
  (count and chunk agree);
* ``cms-categories`` / ``cms-tags`` archive providers are off by default (no
  chunk in ``/sitemap.xml``); switched on they list ``/category/<slug>`` and
  ``/tag/<slug>`` for terms with ≥1 published post, skipping ``seo_excluded``
  categories and ``sitemap_exclude_terms`` slugs, DB-paged consistently;
* the S56 SEO settings keep working: ``sitemap_include_pages`` is folded into
  ``seo_index_pages`` (PUT mirrors it; GET reports the effective value).

Data goes through services/repositories and the core tags port; config through
the live ``config_store``; the shared conftest restores the cms blob.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov (a switched-off provider is an empty provider, not an error);
clean code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import re
import uuid

import pytest
from flask import current_app

from plugins.cms.src.models.cms_post import (
    CmsPost,
    POST_STATUS_DRAFT,
    POST_STATUS_PUBLISHED,
)
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import (
    post_type_registry,
    seo_registry,
    term_type_registry,
)
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services.term_type_registry import TermType

SETTINGS_URL = "/api/v1/admin/cms/seo/settings"


@pytest.fixture(autouse=True)
def _registries():
    post_snapshot = list(post_type_registry.list_post_types())
    term_snapshot = list(term_type_registry.list_term_types())
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
    for post_type in post_snapshot:
        post_type_registry.register_post_type(post_type)
    for term_type in term_snapshot:
        term_type_registry.register_term_type(term_type)


@pytest.fixture
def admin_headers(client, db):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    data = response.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _suffix():
    return uuid.uuid4().hex[:8]


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
    )


def _create_post(db, post_type, slug, status=POST_STATUS_PUBLISHED, term_ids=None):
    service = _post_service(db)
    created = service.create_post(
        {"type": post_type, "slug": slug, "title": f"Title {slug}", "status": status}
    )
    if term_ids:
        service.assign_terms(created["id"], term_ids)
    db.session.commit()
    return created


def _create_category(db, slug, seo_excluded=False):
    term = TermService(repo=TermRepository(db.session)).create_term(
        {
            "term_type": "category",
            "name": slug,
            "slug": slug,
            "seo_excluded": seo_excluded,
        }
    )
    db.session.commit()
    return term


def _tag_post(app, post_id, tag_slug):
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "cms_post", uuid.UUID(post_id), [tag_slug]
        )


def _save_cms_config(**values):
    store = current_app.config_store
    store.save_config("cms", {**(store.get_config("cms") or {}), **values})


def _locs(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return re.findall(r"<loc>([^<]+)</loc>", response.get_data(as_text=True))


def _paths(client, path):
    return {loc.split("://", 1)[-1].split("/", 1)[-1] for loc in _locs(client, path)}


def _all_paths(provider):
    return [
        entry.loc.split("://", 1)[-1] for entry in provider.page(0, provider.count())
    ]


# ── pages / posts switches on the ``cms`` provider ───────────────────────────


def test_index_pages_off_drops_pages_in_sql(client, db):
    page_slug, post_slug = f"page-{_suffix()}", f"post-{_suffix()}"
    _create_post(db, "page", page_slug)
    _create_post(db, "post", post_slug)
    cms_provider = seo_registry.find_sitemap_provider("cms")
    count_with_pages = cms_provider.count()

    _save_cms_config(seo_index_pages=False)

    published_pages = (
        db.session.query(CmsPost)
        .filter(CmsPost.type == "page", CmsPost.status == POST_STATUS_PUBLISHED)
        .count()
    )
    assert cms_provider.count() == count_with_pages - published_pages
    paths = _paths(client, "/sitemap-cms-1.xml")
    assert post_slug in paths
    assert page_slug not in paths


def test_index_posts_off_drops_posts(client, db):
    page_slug, post_slug = f"page-{_suffix()}", f"post-{_suffix()}"
    _create_post(db, "page", page_slug)
    _create_post(db, "post", post_slug)

    _save_cms_config(seo_index_posts=False)

    paths = _paths(client, "/sitemap-cms-1.xml")
    assert page_slug in paths
    assert post_slug not in paths


# ── category / tag archive providers ─────────────────────────────────────────


def test_term_archive_chunks_are_absent_by_default(client, db):
    category = _create_category(db, f"cat-{_suffix()}")
    created = _create_post(db, "post", f"post-{_suffix()}", term_ids=[category["id"]])
    _tag_post(current_app, created["id"], f"tag-{_suffix()}")

    index_locs = _locs(client, "/sitemap.xml")

    assert not any("sitemap-cms-categories-" in loc for loc in index_locs)
    assert not any("sitemap-cms-tags-" in loc for loc in index_locs)
    assert client.get("/sitemap-cms-categories-1.xml").status_code == 404


def test_categories_on_lists_published_category_archives(client, db):
    listed = _create_category(db, f"cat-listed-{_suffix()}")
    draft_only = _create_category(db, f"cat-draft-{_suffix()}")
    excluded = _create_category(db, f"cat-excluded-{_suffix()}", seo_excluded=True)
    filtered = _create_category(db, f"cat-filtered-{_suffix()}")
    _create_post(db, "post", f"p-{_suffix()}", term_ids=[listed["id"]])
    _create_post(db, "post", f"p-{_suffix()}", POST_STATUS_DRAFT, [draft_only["id"]])
    _create_post(db, "post", f"p-{_suffix()}", term_ids=[excluded["id"]])
    _create_post(db, "post", f"p-{_suffix()}", term_ids=[filtered["id"]])

    _save_cms_config(
        seo_index_categories=True, sitemap_exclude_terms=[filtered["slug"]]
    )

    index_locs = _locs(client, "/sitemap.xml")
    assert any(loc.endswith("/sitemap-cms-categories-1.xml") for loc in index_locs)
    assert not any("sitemap-cms-tags-" in loc for loc in index_locs)
    paths = _paths(client, "/sitemap-cms-categories-1.xml")
    assert f"category/{listed['slug']}" in paths
    assert f"category/{draft_only['slug']}" not in paths
    assert f"category/{excluded['slug']}" not in paths
    assert f"category/{filtered['slug']}" not in paths


def test_tags_on_lists_tag_archives_of_published_posts(client, db):
    published_tag, draft_tag = f"tag-pub-{_suffix()}", f"tag-draft-{_suffix()}"
    published = _create_post(db, "post", f"p-{_suffix()}")
    draft = _create_post(db, "post", f"p-{_suffix()}", POST_STATUS_DRAFT)
    _tag_post(current_app, published["id"], published_tag)
    _tag_post(current_app, draft["id"], draft_tag)

    _save_cms_config(seo_index_tags=True)

    index_locs = _locs(client, "/sitemap.xml")
    assert any(loc.endswith("/sitemap-cms-tags-1.xml") for loc in index_locs)
    paths = _paths(client, "/sitemap-cms-tags-1.xml")
    assert f"tag/{published_tag}" in paths
    assert f"tag/{draft_tag}" not in paths


@pytest.mark.parametrize(
    "provider_name, switch_key",
    [("cms-categories", "seo_index_categories"), ("cms-tags", "seo_index_tags")],
)
def test_archive_paging_is_consistent_with_count(db, provider_name, switch_key):
    for _ in range(3):
        category = _create_category(db, f"cat-{_suffix()}")
        created = _create_post(db, "post", f"p-{_suffix()}", term_ids=[category["id"]])
        _tag_post(current_app, created["id"], f"tag-{_suffix()}")
    _save_cms_config(**{switch_key: True})
    provider = seo_registry.find_sitemap_provider(provider_name)

    total = provider.count()
    windowed = [
        entry.loc.split("://", 1)[-1]
        for offset in range(0, total, 2)
        for entry in provider.page(offset, 2)
    ]

    assert total >= 3
    assert len(windowed) == total
    assert windowed == _all_paths(provider)
    assert len(set(windowed)) == total


# ── S56 settings stay coherent with the new pages switch ─────────────────────


def test_settings_put_include_pages_mirrors_into_the_new_switch(
    client, db, admin_headers
):
    _save_cms_config(seo_index_pages=True)
    page_slug, post_slug = f"page-{_suffix()}", f"post-{_suffix()}"
    _create_post(db, "page", page_slug)
    _create_post(db, "post", post_slug)

    response = client.put(
        SETTINGS_URL, json={"sitemap_include_pages": False}, headers=admin_headers
    )

    assert response.status_code == 200
    assert current_app.config_store.get_config("cms")["seo_index_pages"] is False
    paths = _paths(client, "/sitemap-cms-1.xml")
    assert post_slug in paths
    assert page_slug not in paths


def test_settings_get_reports_the_effective_include_pages(client, db, admin_headers):
    _save_cms_config(seo_index_pages=False, sitemap_include_pages=True)

    settings = client.get(SETTINGS_URL, headers=admin_headers).get_json()

    assert settings["sitemap_include_pages"] is False
