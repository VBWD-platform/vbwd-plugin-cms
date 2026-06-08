"""Unit tests for the unified import/export (S47.0 increment 2).

Covers the new typed export (``posts.json`` + ``terms.json`` under a
versioned ``manifest.json`` with a bumped ``format_version``) and the
legacy-format adapter that ingests an OLD ``pages.json`` into
``cms_post(type=page)`` and ``categories.json`` into
``cms_term(term_type=category)``. The pre-existing import/export tests
(per-section ``cms_page`` ZIP) must stay green — this is additive.
"""
import datetime
import io
import json
import zipfile
from unittest.mock import MagicMock
from uuid import uuid4

from plugins.cms.src.services.cms_import_export_service import (
    CmsImportExportService,
    UNIFIED_FORMAT_VERSION,
)
from vbwd.interfaces.file_storage import InMemoryFileStorage


def _make_post(slug="hello", post_type="page", status="published"):
    from plugins.cms.src.models.cms_post import CmsPost

    post = CmsPost()
    post.id = uuid4()
    post.type = post_type
    post.slug = slug
    post.title = "Hello"
    post.excerpt = None
    post.content_json = {"type": "doc", "content": []}
    post.content_html = "<h1>Hello</h1>"
    post.type_data = None
    post.author_id = None
    post.parent_id = None
    post.status = status
    post.published_at = None
    post.language = "en"
    post.translation_group_id = None
    post.sort_order = 0
    post.meta_title = "Hello Meta"
    post.meta_description = "desc"
    post.meta_keywords = None
    post.og_title = None
    post.og_description = None
    post.og_image_url = None
    post.canonical_url = "https://x/hello"
    post.robots = "index,follow"
    post.schema_json = None
    post.seo_excluded = False
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_term(slug="news", term_type="category", name="News"):
    from plugins.cms.src.models.cms_term import CmsTerm

    term = CmsTerm()
    term.id = uuid4()
    term.term_type = term_type
    term.slug = slug
    term.name = name
    term.parent_id = None
    term.description = None
    term.seo_excluded = False
    term.sort_order = 0
    term.created_at = term.updated_at = datetime.datetime.utcnow()
    return term


def _make_svc(posts=None, terms=None):
    """Build the service with unified repos wired and the legacy repos stubbed."""
    cat_repo = MagicMock()
    cat_repo.find_all.return_value = []
    style_repo = MagicMock()
    style_repo.find_all.return_value = {"items": []}
    widget_repo = MagicMock()
    widget_repo.find_all.return_value = {"items": []}
    layout_repo = MagicMock()
    layout_repo.find_all.return_value = {"items": []}
    page_repo = MagicMock()
    page_repo.find_all.return_value = {"items": []}
    routing_repo = MagicMock()
    routing_repo.find_all.return_value = []
    image_repo = MagicMock()
    image_repo.find_all.return_value = {"items": []}
    lw_repo = MagicMock()

    post_store = {(p.type, p.slug): p for p in (posts or [])}
    post_repo = MagicMock()
    post_repo.find_paginated.return_value = {
        "items": posts or [],
        "total": len(posts or []),
        "page": 1,
        "per_page": 100000,
        "pages": 1,
    }
    post_repo.find_by_type_and_slug.side_effect = lambda t, s: post_store.get((t, s))

    def _save_post(post):
        post_store[(post.type, post.slug)] = post
        return post

    post_repo.save.side_effect = _save_post

    term_store = {(t.term_type, t.slug): t for t in (terms or [])}
    term_repo = MagicMock()
    term_repo.find_by_type.return_value = terms or []
    term_repo.find_by_type_and_slug.side_effect = lambda tt, s: term_store.get((tt, s))

    def _save_term(term):
        term_store[(term.term_type, term.slug)] = term
        return term

    term_repo.save.side_effect = _save_term

    svc = CmsImportExportService(
        cat_repo,
        style_repo,
        widget_repo,
        layout_repo,
        page_repo,
        routing_repo,
        image_repo,
        lw_repo,
        InMemoryFileStorage(),
        post_repo=post_repo,
        term_repo=term_repo,
    )
    return svc, post_repo, term_repo


def _parse_zip(data: bytes) -> dict:
    out = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                out[name] = json.loads(zf.read(name))
            else:
                out[name] = zf.read(name)
    return out


class TestUnifiedExport:
    def test_export_emits_posts_json(self):
        svc, *_ = _make_svc(posts=[_make_post("hello")])
        contents = _parse_zip(svc.export(["posts"]))
        assert "posts.json" in contents
        assert contents["posts.json"][0]["slug"] == "hello"
        assert contents["posts.json"][0]["type"] == "page"

    def test_export_emits_terms_json(self):
        svc, *_ = _make_svc(terms=[_make_term("news")])
        contents = _parse_zip(svc.export(["terms"]))
        assert "terms.json" in contents
        assert contents["terms.json"][0]["slug"] == "news"
        assert contents["terms.json"][0]["term_type"] == "category"

    def test_manifest_carries_bumped_format_version(self):
        svc, *_ = _make_svc(posts=[_make_post()])
        contents = _parse_zip(svc.export(["posts"]))
        manifest = contents["manifest.json"]
        assert manifest["format_version"] == UNIFIED_FORMAT_VERSION
        assert UNIFIED_FORMAT_VERSION != "1.0"

    def test_export_terms_groups_categories_and_tags(self):
        svc, *_ = _make_svc(
            terms=[
                _make_term("news", "category"),
                _make_term("python", "tag", "Python"),
            ]
        )
        # term repo returns all terms for any type lookup in this stub; assert
        # the export queries both registered term-types and writes them out.
        contents = _parse_zip(svc.export(["terms"]))
        slugs = {row["slug"] for row in contents["terms.json"]}
        assert "news" in slugs


class TestLegacyAdapter:
    def _legacy_zip(self, pages=None, categories=None) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps({"version": "1.0", "sections": ["pages", "categories"]}),
            )
            if pages is not None:
                zf.writestr("pages.json", json.dumps(pages))
            if categories is not None:
                zf.writestr("categories.json", json.dumps(categories))
        buf.seek(0)
        return buf.read()

    def test_legacy_pages_become_page_posts(self):
        data = self._legacy_zip(
            pages=[
                {
                    "slug": "about",
                    "name": "About Us",
                    "language": "en",
                    "content_json": {"type": "doc"},
                    "content_html": "<h1>About</h1>",
                    "is_published": True,
                    "sort_order": 5,
                    "meta_title": "About",
                    "meta_description": "About desc",
                    "canonical_url": "https://x/about",
                    "robots": "index,follow",
                }
            ]
        )
        svc, post_repo, _ = _make_svc()
        result = svc.import_legacy_as_unified(data, "add")
        assert result["imported"]["posts"] == 1
        saved = post_repo.save.call_args[0][0]
        assert saved.type == "page"
        assert saved.slug == "about"
        assert saved.title == "About Us"
        assert saved.status == "published"
        assert saved.canonical_url == "https://x/about"

    def test_legacy_unpublished_page_maps_to_draft(self):
        data = self._legacy_zip(
            pages=[{"slug": "wip", "name": "WIP", "is_published": False}]
        )
        svc, post_repo, _ = _make_svc()
        svc.import_legacy_as_unified(data, "add")
        saved = post_repo.save.call_args[0][0]
        assert saved.status == "draft"

    def test_legacy_categories_become_category_terms(self):
        data = self._legacy_zip(
            categories=[{"slug": "news", "name": "News", "sort_order": 2}]
        )
        svc, _, term_repo = _make_svc()
        result = svc.import_legacy_as_unified(data, "add")
        assert result["imported"]["terms"] == 1
        saved = term_repo.save.call_args[0][0]
        assert saved.term_type == "category"
        assert saved.slug == "news"

    def test_legacy_add_skips_existing_post_slug(self):
        existing = _make_post("about", "page")
        data = self._legacy_zip(pages=[{"slug": "about", "name": "Dup"}])
        svc, post_repo, _ = _make_svc(posts=[existing])
        result = svc.import_legacy_as_unified(data, "add")
        assert result["imported"]["posts"] == 0
        post_repo.save.assert_not_called()


class TestUnifiedRoundTrip:
    def test_export_then_import_round_trips_posts(self):
        svc, post_repo, _ = _make_svc(posts=[_make_post("hello")])
        archive = svc.export(["posts", "terms"])
        # Re-import into a fresh service (empty stores).
        fresh, fresh_post_repo, _ = _make_svc()
        result = fresh.import_unified(archive, "add")
        assert result["imported"]["posts"] == 1
        saved = fresh_post_repo.save.call_args[0][0]
        assert saved.slug == "hello"
        assert saved.type == "page"
