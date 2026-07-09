"""Integration: the shared ``terms-archive`` layout + TermArchive widget seed.

Inc 1 of the CMS term-archives feature serves category archives at
``/category/<slug>`` and tag archives at ``/tag/<slug>`` DYNAMICALLY through the
fe catch-all — NO per-term page is seeded. What must be seeded is ONE shared
``terms-archive`` layout that places a single route-driven ``TermArchive``
vue-component widget in its ``archive`` area; that one layout renders every
category AND tag archive.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL, cold local + CI; seeded through the CMS services);
SOLID/DI/DRY; Liskov; clean code; no overengineering (no per-term page). Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin.populate_cms import (
    populate_cms,
    TERMS_ARCHIVE_LAYOUT_SLUG,
    TERMS_ARCHIVE_WIDGET_SLUG,
)
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.models.cms_widget import CmsWidget


class TestSeedTermsArchiveLayout:
    def test_seed_creates_the_shared_terms_archive_layout(self, db):
        populate_cms()
        layout = (
            db.session.query(CmsLayout)
            .filter_by(slug=TERMS_ARCHIVE_LAYOUT_SLUG)
            .one_or_none()
        )
        assert layout is not None, "terms-archive layout not seeded"
        assert layout.is_active is True

    def test_layout_places_the_term_archive_widget_in_the_archive_area(self, db):
        populate_cms()
        layout = (
            db.session.query(CmsLayout).filter_by(slug=TERMS_ARCHIVE_LAYOUT_SLUG).one()
        )
        widget = (
            db.session.query(CmsWidget)
            .filter_by(slug=TERMS_ARCHIVE_WIDGET_SLUG)
            .one_or_none()
        )
        assert widget is not None, "TermArchive widget record not seeded"
        assert widget.content_json.get("component") == "TermArchive"

        placement = (
            db.session.query(CmsLayoutWidget)
            .filter_by(layout_id=layout.id, widget_id=widget.id)
            .one_or_none()
        )
        assert placement is not None, "TermArchive widget not placed on the layout"
        assert placement.area_name == "archive"

    def test_no_page_is_backed_by_the_terms_archive_layout(self, db):
        populate_cms()
        # The archive is served DYNAMICALLY through the fe catch-all — the shared
        # terms-archive layout must never be seeded as the layout of a backing
        # cms_post (that would be a per-term/archive page, which we do not build).
        layout = (
            db.session.query(CmsLayout).filter_by(slug=TERMS_ARCHIVE_LAYOUT_SLUG).one()
        )
        backing = db.session.query(CmsPost).filter_by(layout_id=layout.id).count()
        assert backing == 0, "terms-archive layout must not back any seeded page"

    def test_seed_is_idempotent_for_the_layout_and_widget(self, db):
        populate_cms()
        populate_cms()
        layout_count = (
            db.session.query(CmsLayout)
            .filter_by(slug=TERMS_ARCHIVE_LAYOUT_SLUG)
            .count()
        )
        widget_count = (
            db.session.query(CmsWidget)
            .filter_by(slug=TERMS_ARCHIVE_WIDGET_SLUG)
            .count()
        )
        assert layout_count == 1, "terms-archive layout duplicated on re-seed"
        assert widget_count == 1, "TermArchive widget duplicated on re-seed"
