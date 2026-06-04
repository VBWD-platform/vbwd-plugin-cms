"""Integration tests for the cms_page -> cms_post backfill (S47.0, real PG).

A seeded ``cms_page`` (and ``cms_category``) set is folded into the unified
tables; the legacy rows stay intact; the run is idempotent. Exercises the
service against a real PostgreSQL session via the ``db`` fixture.
"""
import uuid

from plugins.cms.src.models.cms_page import CmsPage
from plugins.cms.src.models.cms_category import CmsCategory
from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.cms_backfill_service import CmsBackfillService


def _seed_page(db, slug, is_published=True):
    page = CmsPage(
        slug=slug,
        name=f"Title {slug}",
        language="en",
        content_json={"type": "doc", "content": []},
        content_html=f"<h1>{slug}</h1>",
        is_published=is_published,
        sort_order=3,
        meta_title=f"{slug} meta",
        meta_description=f"{slug} description",
        canonical_url=f"https://example.test/{slug}",
        robots="index,follow",
    )
    db.session.add(page)
    db.session.commit()
    return page


def _seed_category(db, slug):
    cat = CmsCategory(slug=slug, name=f"Cat {slug}", sort_order=1)
    db.session.add(cat)
    db.session.commit()
    return cat


def _service(db):
    return CmsBackfillService(
        page_repo=CmsPageRepository(db.session),
        category_repo=CmsCategoryRepository(db.session),
        post_repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
    )


class TestBackfillCompleteness:
    def test_page_becomes_page_post_with_seo(self, db):
        slug = f"about-{uuid.uuid4().hex[:8]}"
        _seed_page(db, slug, is_published=True)
        _service(db).backfill()

        post = PostRepository(db.session).find_by_type_and_slug("page", slug)
        assert post is not None
        assert post.status == "published"
        assert post.title == f"Title {slug}"
        assert post.canonical_url == f"https://example.test/{slug}"
        assert post.meta_description == f"{slug} description"

    def test_unpublished_page_becomes_draft(self, db):
        slug = f"wip-{uuid.uuid4().hex[:8]}"
        _seed_page(db, slug, is_published=False)
        _service(db).backfill()
        post = PostRepository(db.session).find_by_type_and_slug("page", slug)
        assert post is not None
        assert post.status == "draft"

    def test_category_becomes_category_term(self, db):
        slug = f"news-{uuid.uuid4().hex[:8]}"
        _seed_category(db, slug)
        _service(db).backfill()
        term = TermRepository(db.session).find_by_type_and_slug("category", slug)
        assert term is not None
        assert term.name == f"Cat {slug}"

    def test_legacy_rows_remain_intact(self, db):
        slug = f"keep-{uuid.uuid4().hex[:8]}"
        _seed_page(db, slug)
        _service(db).backfill()
        # The original cms_page row is untouched (copy, not move).
        assert CmsPageRepository(db.session).find_by_slug(slug) is not None


class TestBackfillIdempotency:
    def test_rerun_creates_no_duplicates(self, db):
        slug = f"idem-{uuid.uuid4().hex[:8]}"
        _seed_page(db, slug)
        service = _service(db)
        first = service.backfill()
        assert first["pages_copied"] >= 1

        second = service.backfill()
        # The just-seeded slug is skipped on the 2nd pass.
        existing = PostRepository(db.session).find_paginated(
            post_type="page", per_page=100000
        )
        matching = [p for p in existing["items"] if p.slug == slug]
        assert len(matching) == 1
        assert second["pages_copied"] == 0 or all(
            p.slug != slug for p in existing["items"][1:]
        )
