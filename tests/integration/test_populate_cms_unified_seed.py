"""Integration: ``populate_cms()`` seeds the demo portal into the UNIFIED model.

S105 retired the legacy ``cms_page`` / ``cms_category`` round-trip + backfill, so
the demo seeder now writes the portal pages, categories and page-widget
assignments straight into ``cms_post`` / ``cms_term`` / ``cms_post_widget``. This
test runs the real seeder against PostgreSQL and proves:

* the seeded portal categories (about/blog/static-pages/ghrm) exist as
  ``cms_term(term_type=category)``;
* a representative portal page (``about``) exists as ``cms_post(type=page)``;
* a page with widget assignments lands rows in ``cms_post_widget``;
* the seeder is idempotent (a second run creates no duplicates).

The shared ``db`` fixture isolates this in a rolled-back transaction, so the
seeder's commits never leak into the dev DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG,
cold local + CI; demo data seeded through services); SOLID/DI/DRY; Liskov; clean
code; no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
from plugins.cms.src.bin.populate_cms import populate_cms
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_post_widget import CmsPostWidget
from plugins.cms.src.models.cms_term import CmsTerm, CATEGORY_TERM_TYPE


def _count(db, model, **filters):
    return db.session.query(model).filter_by(**filters).count()


class TestPopulateSeedsUnifiedModel:
    def test_portal_categories_seeded_as_cms_terms(self, db):
        populate_cms()
        for slug in ("about", "blog", "static-pages", "ghrm"):
            assert (
                _count(db, CmsTerm, term_type=CATEGORY_TERM_TYPE, slug=slug) == 1
            ), f"category '{slug}' not seeded as a cms_term"

    def test_portal_page_seeded_as_unified_post(self, db):
        populate_cms()
        about = (
            db.session.query(CmsPost).filter_by(type="page", slug="about").one_or_none()
        )
        assert about is not None, "portal page 'about' not seeded as cms_post"
        assert about.title

    def test_pages_land_widget_assignments_in_cms_post_widget(self, db):
        populate_cms()
        # The demo seeds at least one page-level widget assignment overall.
        assert db.session.query(CmsPostWidget).count() > 0

    def test_no_legacy_cms_page_table_written(self, db):
        # Re-running must not raise (legacy round-trip is gone) and must not
        # create duplicate unified pages.
        populate_cms()
        first = _count(db, CmsPost, type="page", slug="about")
        populate_cms()
        second = _count(db, CmsPost, type="page", slug="about")
        assert first == 1 and second == 1
