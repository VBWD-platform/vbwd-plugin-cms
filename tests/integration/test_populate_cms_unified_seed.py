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
from plugins.cms.src.bin.populate_cms import populate_cms, _build_unified_services
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_post_widget import CmsPostWidget
from plugins.cms.src.models.cms_term import CmsTerm, CATEGORY_TERM_TYPE
from plugins.cms.src.models.cms_widget import CmsWidget


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


class TestSearchDemoLayoutsPersisted:
    """S121 §4.5 — the demo ``docs`` page must persist the quicksearch
    ``config_override`` onto its ``cms_post_widget`` row, proving the seeder's
    page-widget assignment path carries per-placement overrides end-to-end
    (not just the fixture)."""

    def test_docs_page_widget_persists_quicksearch_config_override(self, db):
        populate_cms()
        docs = (
            db.session.query(CmsPost).filter_by(type="page", slug="docs").one_or_none()
        )
        assert docs is not None, "demo 'docs' page not seeded"
        assignment = (
            db.session.query(CmsPostWidget)
            .filter_by(post_id=docs.id, area_name="sidebar")
            .one_or_none()
        )
        assert assignment is not None, "docs sidebar search widget not assigned"
        override = assignment.config_override
        assert override is not None
        # Defect 1 — the persisted vue-widget override is NESTED under ``config``
        # so the fe-user renderer (which merges ``override.config``) applies it.
        assert "quicksearch" not in override, "override must be nested under 'config'"
        nested = override["config"]
        assert nested["quicksearch"] is True
        assert nested["scope"] == "both"
        assert nested["quicksearch_limit"] == 6


class TestDocsPageRepointedToDocsLayout:
    """S121 Defect 2 — a real documentation-portal ``docs`` page pre-dates this
    seed (on another layout). The seeder RE-POINTS that existing page onto the
    "Docs pages" layout and gives it a quicksearch sidebar, WITHOUT wiping its
    title/body or its other widgets. The repoint is narrow (only ``layout_id`` +
    the sidebar Search assignment) and idempotent."""

    _PORTAL_BODY = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "REAL PORTAL DOCS BODY"}],
            }
        ],
    }

    def _seed_preexisting_docs_page(self):
        """Create a ``docs`` page on NO docs layout (simulating the pre-existing
        portal page) straight through the unified service, then commit."""
        post_service, _term, _pr, _tr, _pw = _build_unified_services()
        post_service.create_post(
            {
                "type": "page",
                "slug": "docs",
                "title": "Documentation Portal",
                "language": "en",
                "content_json": self._PORTAL_BODY,
                "status": "published",
                "layout_id": None,
            }
        )

    def test_existing_docs_page_is_repointed_body_preserved(self, db):
        self._seed_preexisting_docs_page()
        db.session.commit()

        populate_cms()

        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        # Title + body preserved — the repoint never overwrites page content.
        assert docs.title == "Documentation Portal"
        assert docs.content_json == self._PORTAL_BODY
        # Re-pointed onto the "Docs pages" layout.
        docs_layout = db.session.query(CmsLayout).filter_by(slug="docs").one()
        assert str(docs.layout_id) == str(docs_layout.id)
        assert docs_layout.name == "Docs pages"
        # The sidebar holds the Search box with the NESTED quicksearch override.
        sidebar = (
            db.session.query(CmsPostWidget)
            .filter_by(post_id=docs.id, area_name="sidebar")
            .one()
        )
        nested = sidebar.config_override["config"]
        assert nested["quicksearch"] is True
        assert nested["scope"] == "both"
        assert nested["quicksearch_limit"] == 6

    def test_repoint_is_idempotent_and_preserves_other_widgets(self, db):
        self._seed_preexisting_docs_page()
        db.session.commit()
        populate_cms()

        _ps, _ts, _pr, _tr, post_widget_repo = _build_unified_services()
        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()

        # Simulate an operator-added extra widget in another area of the page.
        footer = db.session.query(CmsWidget).filter_by(slug="footer-nav").one()
        rows = [
            {
                "widget_id": str(row.widget_id),
                "area_name": row.area_name,
                "sort_order": row.sort_order,
                "required_access_level_ids": row.required_access_level_ids,
                "config_override": row.config_override,
            }
            for row in post_widget_repo.find_by_post(str(docs.id))
        ]
        rows.append(
            {
                "widget_id": str(footer.id),
                "area_name": "footer",
                "sort_order": len(rows),
                "config_override": None,
            }
        )
        post_widget_repo.replace_for_post(str(docs.id), rows)

        # Re-run the whole seed — must be a no-op for the docs page.
        populate_cms()

        assert (
            db.session.query(CmsPost).filter_by(type="page", slug="docs").count() == 1
        ), "repoint must not create a second docs page"
        after = post_widget_repo.find_by_post(str(docs.id))
        by_area = {}
        for row in after:
            by_area.setdefault(row.area_name, []).append(row)
        # Sidebar Search preserved and NOT duplicated.
        assert len(by_area.get("sidebar", [])) == 1
        # The operator's footer widget survived the re-seed.
        assert len(by_area.get("footer", [])) == 1
        # Body still intact.
        assert docs.content_json == self._PORTAL_BODY
