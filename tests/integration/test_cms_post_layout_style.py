"""Integration: cms_post gains layout/style (same as cms_page), real PG.

Posts must carry a layout/style/theme-switcher capability identical to pages
(user feedback: "posts must have theme style and layout, same like pages").
This exercises the new columns end-to-end: they persist, serialize, and the
backfill copies them from the originating cms_page.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, schema only via Alembic, no raw SQL
for data); SOLID/DI/DRY; Liskov (the new columns honour the cms_page contract);
clean code; no overengineering (3 columns mirrored, nothing more). Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_page import CmsPage
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_style import CmsStyle
from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.cms_backfill_service import CmsBackfillService


def _seed_layout(db, slug):
    layout = CmsLayout(slug=slug, name=f"Layout {slug}", areas=[])
    db.session.add(layout)
    db.session.commit()
    return layout


def _seed_style(db, slug):
    style = CmsStyle(slug=slug, name=f"Style {slug}", source_css=".x{}")
    db.session.add(style)
    db.session.commit()
    return style


class TestPostLayoutStylePersistence:
    def test_columns_persist_and_serialize(self, db):
        layout = _seed_layout(db, f"l-{uuid.uuid4().hex[:8]}")
        style = _seed_style(db, f"s-{uuid.uuid4().hex[:8]}")
        slug = f"persist-{uuid.uuid4().hex[:8]}"
        post = CmsPost(
            type="post",
            slug=slug,
            title="Layout Post",
            content_json={},
            layout_id=layout.id,
            style_id=style.id,
        )
        db.session.add(post)
        db.session.commit()

        loaded = PostRepository(db.session).find_by_type_and_slug("post", slug)
        assert str(loaded.layout_id) == str(layout.id)
        assert str(loaded.style_id) == str(style.id)

        data = loaded.to_dict()
        assert data["layout_id"] == str(layout.id)
        assert data["style_id"] == str(style.id)

    def test_layout_style_default_unset(self, db):
        slug = f"default-{uuid.uuid4().hex[:8]}"
        post = CmsPost(type="post", slug=slug, title="Default", content_json={})
        db.session.add(post)
        db.session.commit()
        loaded = PostRepository(db.session).find_by_type_and_slug("post", slug)
        assert loaded.layout_id is None
        assert loaded.style_id is None


def _backfill_service(db):
    return CmsBackfillService(
        page_repo=CmsPageRepository(db.session),
        category_repo=CmsCategoryRepository(db.session),
        post_repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
    )


class TestBackfillCopiesLayoutStyle:
    def test_backfill_copies_layout_style_from_page(self, db):
        layout = _seed_layout(db, f"bl-{uuid.uuid4().hex[:8]}")
        style = _seed_style(db, f"bs-{uuid.uuid4().hex[:8]}")
        slug = f"bf-{uuid.uuid4().hex[:8]}"
        page = CmsPage(
            slug=slug,
            name="BF Page",
            content_json={},
            content_html=f"<p>{slug}</p>",
            is_published=True,
            layout_id=layout.id,
            style_id=style.id,
        )
        db.session.add(page)
        db.session.commit()

        _backfill_service(db).backfill()

        post = PostRepository(db.session).find_by_type_and_slug("page", slug)
        assert str(post.layout_id) == str(layout.id)
        assert str(post.style_id) == str(style.id)

    def test_backfill_is_idempotent_and_updates_layout(self, db):
        layout_a = _seed_layout(db, f"ia-{uuid.uuid4().hex[:8]}")
        layout_b = _seed_layout(db, f"ib-{uuid.uuid4().hex[:8]}")
        slug = f"idem-{uuid.uuid4().hex[:8]}"
        page = CmsPage(
            slug=slug,
            name="Idem",
            content_json={},
            content_html=f"<p>{slug}</p>",
            is_published=True,
            layout_id=layout_a.id,
        )
        db.session.add(page)
        db.session.commit()

        _backfill_service(db).backfill()
        post = PostRepository(db.session).find_by_type_and_slug("page", slug)
        assert str(post.layout_id) == str(layout_a.id)

        # Page's layout changes; a re-run must update the already-migrated post
        # (idempotent re-apply of layout/style/theme, no duplicate row).
        page.layout_id = layout_b.id
        db.session.commit()
        _backfill_service(db).backfill()

        posts = PostRepository(db.session).find_paginated(
            post_type="page", per_page=100000
        )["items"]
        matching = [p for p in posts if p.slug == slug]
        assert len(matching) == 1
        assert str(matching[0].layout_id) == str(layout_b.id)
