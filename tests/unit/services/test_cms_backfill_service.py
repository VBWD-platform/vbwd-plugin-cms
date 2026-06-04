"""Unit tests for CmsBackfillService (S47.0 increment 2).

The backfill copies live ``cms_page`` rows into ``cms_post(type=page)`` and
``cms_category`` rows into ``cms_term(term_type=category)``, idempotently.
These tests pin the column mapping (is_published -> status, SEO 1:1) and the
re-run safety (the 2nd pass creates nothing new), using MagicMock repos so no
DB is required.
"""
import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from plugins.cms.src.models.cms_page import CmsPage
from plugins.cms.src.models.cms_category import CmsCategory
from plugins.cms.src.services.cms_backfill_service import CmsBackfillService


def _make_page(slug="about", name="About Us", is_published=True, **overrides):
    page = CmsPage()
    page.id = uuid4()
    page.slug = slug
    page.name = name
    page.language = overrides.get("language", "en")
    page.content_json = overrides.get("content_json", {"type": "doc", "content": []})
    page.content_html = overrides.get("content_html", "<h1>About</h1>")
    page.is_published = is_published
    page.sort_order = overrides.get("sort_order", 7)
    page.meta_title = overrides.get("meta_title", "About — Meta")
    page.meta_description = overrides.get("meta_description", "About description")
    page.meta_keywords = overrides.get("meta_keywords", "about,us")
    page.og_title = overrides.get("og_title", "About OG")
    page.og_description = overrides.get("og_description", "About OG desc")
    page.og_image_url = overrides.get("og_image_url", "https://x/og.png")
    page.canonical_url = overrides.get("canonical_url", "https://x/about")
    page.robots = overrides.get("robots", "index,follow")
    page.schema_json = overrides.get("schema_json", {"@type": "WebPage"})
    page.created_at = page.updated_at = datetime.datetime.utcnow()
    return page


def _make_category(slug="news", name="News", **overrides):
    cat = CmsCategory()
    cat.id = uuid4()
    cat.slug = slug
    cat.name = name
    cat.parent_id = overrides.get("parent_id")
    cat.sort_order = overrides.get("sort_order", 3)
    cat.created_at = cat.updated_at = datetime.datetime.utcnow()
    return cat


def _make_service(
    pages=None, categories=None, existing_posts=None, existing_terms=None
):
    page_repo = MagicMock()
    page_repo.find_all.return_value = {
        "items": pages or [],
        "total": len(pages or []),
        "page": 1,
        "per_page": 100000,
        "pages": 1,
    }

    category_repo = MagicMock()
    category_repo.find_all.return_value = categories or []

    post_store = {(p.type, p.slug): p for p in (existing_posts or [])}
    post_repo = MagicMock()
    post_repo.find_by_type_and_slug.side_effect = lambda t, s: post_store.get((t, s))

    def _save_post(post):
        post_store[(post.type, post.slug)] = post
        return post

    post_repo.save.side_effect = _save_post

    term_store = {(t.term_type, t.slug): t for t in (existing_terms or [])}
    term_repo = MagicMock()
    term_repo.find_by_type_and_slug.side_effect = lambda tt, s: term_store.get((tt, s))

    def _save_term(term):
        term_store[(term.term_type, term.slug)] = term
        return term

    term_repo.save.side_effect = _save_term

    service = CmsBackfillService(
        page_repo=page_repo,
        category_repo=category_repo,
        post_repo=post_repo,
        term_repo=term_repo,
    )
    return service, page_repo, category_repo, post_repo, term_repo


class TestPageMapping:
    def test_published_page_maps_to_published_status(self):
        page = _make_page(is_published=True)
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.type == "page"
        assert saved.status == "published"

    def test_unpublished_page_maps_to_draft_status(self):
        page = _make_page(is_published=False)
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.status == "draft"

    def test_name_maps_to_title(self):
        page = _make_page(name="Friendly Title")
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.title == "Friendly Title"

    def test_seo_columns_copied_one_to_one(self):
        page = _make_page()
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.meta_title == page.meta_title
        assert saved.meta_description == page.meta_description
        assert saved.meta_keywords == page.meta_keywords
        assert saved.og_title == page.og_title
        assert saved.og_description == page.og_description
        assert saved.og_image_url == page.og_image_url
        assert saved.canonical_url == page.canonical_url
        assert saved.robots == page.robots
        assert saved.schema_json == page.schema_json

    def test_content_and_slug_copied(self):
        page = _make_page(slug="my-slug")
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.slug == "my-slug"
        assert saved.content_html == page.content_html
        assert saved.content_json == page.content_json

    def test_parent_id_is_null_at_migrate_time(self):
        page = _make_page()
        service, _, _, post_repo, _ = _make_service(pages=[page])
        service.backfill()
        saved = post_repo.save.call_args[0][0]
        assert saved.parent_id is None


class TestCategoryMapping:
    def test_category_maps_to_category_term(self):
        cat = _make_category(slug="news", name="News")
        service, _, _, _, term_repo = _make_service(categories=[cat])
        service.backfill()
        saved = term_repo.save.call_args[0][0]
        assert saved.term_type == "category"
        assert saved.slug == "news"
        assert saved.name == "News"

    def test_category_sort_order_copied(self):
        cat = _make_category(sort_order=42)
        service, _, _, _, term_repo = _make_service(categories=[cat])
        service.backfill()
        saved = term_repo.save.call_args[0][0]
        assert saved.sort_order == 42


class TestIdempotency:
    def test_existing_post_is_not_recreated(self):
        page = _make_page(slug="about", content_html="<h1>About</h1>")
        existing = MagicMock()
        existing.type = "page"
        existing.slug = "about"
        # Same content_html → recognised as the already-backfilled page.
        existing.content_html = "<h1>About</h1>"
        # Steady state: the post's theming already matches the page, so the
        # idempotent re-run must not write anything.
        existing.layout_id = page.layout_id
        existing.style_id = page.style_id
        service, _, _, post_repo, _ = _make_service(
            pages=[page], existing_posts=[existing]
        )
        summary = service.backfill()
        post_repo.save.assert_not_called()
        assert summary["pages_skipped"] == 1
        assert summary["pages_copied"] == 0

    def test_existing_term_is_not_recreated(self):
        cat = _make_category(slug="news")
        existing = MagicMock()
        existing.term_type = "category"
        existing.slug = "news"
        service, _, _, _, term_repo = _make_service(
            categories=[cat], existing_terms=[existing]
        )
        summary = service.backfill()
        term_repo.save.assert_not_called()
        assert summary["categories_skipped"] == 1

    def test_second_pass_creates_nothing_new(self):
        page = _make_page(slug="about")
        cat = _make_category(slug="news")
        service, _, _, post_repo, term_repo = _make_service(
            pages=[page], categories=[cat]
        )
        first = service.backfill()
        assert first["pages_copied"] == 1
        assert first["categories_copied"] == 1
        post_repo.save.reset_mock()
        term_repo.save.reset_mock()
        second = service.backfill()
        assert second["pages_copied"] == 0
        assert second["categories_copied"] == 0
        post_repo.save.assert_not_called()
        term_repo.save.assert_not_called()


class TestBulkSignal:
    def test_at_most_one_bulk_content_changed_signal(self):
        pages = [_make_page(slug=f"p{i}") for i in range(3)]
        dispatcher = MagicMock()
        page_repo = MagicMock()
        page_repo.find_all.return_value = {
            "items": pages,
            "total": 3,
            "page": 1,
            "per_page": 100000,
            "pages": 1,
        }
        category_repo = MagicMock()
        category_repo.find_all.return_value = []
        post_repo = MagicMock()
        post_repo.find_by_type_and_slug.return_value = None
        post_repo.save.side_effect = lambda post: post
        term_repo = MagicMock()
        service = CmsBackfillService(
            page_repo=page_repo,
            category_repo=category_repo,
            post_repo=post_repo,
            term_repo=term_repo,
            event_dispatcher=dispatcher,
        )
        service.backfill()
        # No per-row content.changed storm — at most one bulk signal.
        assert dispatcher.dispatch.call_count <= 1
