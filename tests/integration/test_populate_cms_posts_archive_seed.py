"""Integration: the CMS posts-archive (blog index) page is seeded at posts_root.

A fresh seed must yield a ``cms_post(type=page)`` at the config-driven
``posts_root`` slug (default ``blog``) whose ``layout_id`` points to the new
``posts-archive`` layout, and that layout must place the ``PostArchive``
vue-component widget in its ``archive`` area. The archive renders ALL published
posts through the existing ``GET /cms/posts?type=post`` path — no new endpoint.

The slug is read from the SAME aggregated CMS config the runtime reads
(``current_app.config_store.get_config('cms')``) with the bundled default
``blog`` as fallback, so the seeded page slug can never drift from the runtime
``%root%`` permalink segment (the GHRM 404 trap).

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL, cold local + CI; demo data seeded through the
CMS services); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin.populate_cms import (
    populate_cms,
    POSTS_ARCHIVE_LAYOUT_SLUG,
    POSTS_ARCHIVE_WIDGET_SLUG,
)
from plugins.cms.src.models.cms_post import CmsPost, POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.models.cms_widget import CmsWidget

DEFAULT_POSTS_ROOT = "blog"


def _archive_page(db, slug):
    return db.session.query(CmsPost).filter_by(type="page", slug=slug).one_or_none()


class TestSeedPostsArchivePage:
    def test_seed_creates_archive_page_at_default_posts_root(self, db):
        populate_cms()
        page = _archive_page(db, DEFAULT_POSTS_ROOT)
        assert page is not None, "posts-archive page not seeded at 'blog'"
        assert page.status == POST_STATUS_PUBLISHED
        assert page.title

    def test_archive_page_points_at_posts_archive_layout(self, db):
        populate_cms()
        page = _archive_page(db, DEFAULT_POSTS_ROOT)
        layout = (
            db.session.query(CmsLayout)
            .filter_by(slug=POSTS_ARCHIVE_LAYOUT_SLUG)
            .one_or_none()
        )
        assert layout is not None, "posts-archive layout not seeded"
        assert str(page.layout_id) == str(layout.id)

    def test_posts_archive_layout_places_the_post_archive_widget(self, db):
        populate_cms()
        layout = (
            db.session.query(CmsLayout).filter_by(slug=POSTS_ARCHIVE_LAYOUT_SLUG).one()
        )
        widget = (
            db.session.query(CmsWidget)
            .filter_by(slug=POSTS_ARCHIVE_WIDGET_SLUG)
            .one_or_none()
        )
        assert widget is not None, "PostArchive widget record not seeded"
        assert widget.content_json.get("component") == "PostArchive"

        placement = (
            db.session.query(CmsLayoutWidget)
            .filter_by(layout_id=layout.id, widget_id=widget.id)
            .one_or_none()
        )
        assert placement is not None, "PostArchive widget not placed on the layout"
        assert placement.area_name == "archive"

    def test_seed_is_idempotent_for_the_archive_page(self, db):
        populate_cms()
        populate_cms()
        count = (
            db.session.query(CmsPost)
            .filter_by(type="page", slug=DEFAULT_POSTS_ROOT)
            .count()
        )
        assert count == 1, "archive page duplicated on re-seed"

    def test_seed_honours_an_overridden_posts_root_from_aggregated_config(
        self, db, monkeypatch
    ):
        from flask import current_app

        overridden = "articles"
        monkeypatch.setattr(
            current_app.config_store,
            "get_config",
            lambda plugin_name: (
                {"posts_root": overridden} if plugin_name == "cms" else {}
            ),
        )
        populate_cms()

        page = _archive_page(db, overridden)
        assert page is not None, "archive page not seeded at the overridden slug"
        # The bundled default slug must NOT be seeded when overridden.
        assert _archive_page(db, DEFAULT_POSTS_ROOT) is None
