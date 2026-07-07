"""Integration: the SAFE ``seed_docs_search`` entrypoint is non-destructive.

The full ``populate_cms`` seeder overwrites styles/widgets/layouts, DELETE+
re-inserts the header menu and deletes the ``default`` routing rule — so it can
never run on a live instance. ``seed_docs_search`` lands ONLY the S121 demo
``docs`` / ``search`` layouts, the ``/search`` page and the ``/docs`` re-point,
and every write is CREATE-ONLY or APPEND-ONLY. These tests are the safety proof:

  * it CREATES the demo layouts + re-points ``/docs`` when they are absent;
  * it NEVER overwrites an existing (operator-edited) ``docs`` layout;
  * the re-point preserves every pre-existing ``/docs`` widget;
  * a second run is a no-op (no duplicate layouts / pages / sidebar rows);
  * a missing ``search`` widget degrades to a skip (no crash, no re-point).

Data is seeded THROUGH the unified services / the seeder's own ORM helpers
(never raw SQL); the shared rolled-back ``db`` fixture self-cleans each test.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG,
cold local + CI); SOLID/DI/DRY (reuses populate_cms helpers); Liskov (missing
widget = skip, not a false success); clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin.populate_cms import (
    _STANDALONE_VUE_WIDGETS,
    _build_unified_services,
    _get_or_create_widget,
)
from plugins.cms.src.bin.seed_docs_search import seed_docs_search
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_post_widget import CmsPostWidget
from plugins.cms.src.models.cms_widget import CmsWidget


_PORTAL_BODY = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "REAL PORTAL DOCS BODY"}],
        }
    ],
}


def _seed_search_widgets() -> None:
    """Create the ``search`` + ``search-results`` widget RECORDS via the seeder's
    canonical ORM helper (DRY — the same config the full seeder ships)."""
    for widget in _STANDALONE_VUE_WIDGETS:
        if widget["slug"] in ("search", "search-results"):
            _get_or_create_widget(
                widget["slug"],
                widget["name"],
                widget["widget_type"],
                content_json=widget["content_json"],
                config=widget.get("config"),
            )


def _seed_preexisting_docs_page(layout_id=None) -> None:
    """Create a real portal ``docs`` page (with a body) on ``layout_id`` through
    the unified service, simulating the page that pre-dates this seed."""
    post_service, _term, _pr, _tr, _pw = _build_unified_services()
    post_service.create_post(
        {
            "type": "page",
            "slug": "docs",
            "title": "Documentation Portal",
            "language": "en",
            "content_json": _PORTAL_BODY,
            "status": "published",
            "layout_id": layout_id,
        }
    )


def _sidebar_search_rows(db, docs_post):
    return (
        db.session.query(CmsPostWidget)
        .filter_by(post_id=docs_post.id, area_name="sidebar")
        .all()
    )


class TestCreatesLayoutsAndRepointsWhenAbsent:
    def test_creates_layouts_and_repoints_when_absent(self, db):
        _seed_search_widgets()
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        seed_docs_search()

        docs_layout = db.session.query(CmsLayout).filter_by(slug="docs").one_or_none()
        search_layout = (
            db.session.query(CmsLayout).filter_by(slug="search").one_or_none()
        )
        assert docs_layout is not None, "docs layout not created"
        assert search_layout is not None, "search layout not created"

        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        # Re-pointed onto the docs layout; body preserved.
        assert str(docs.layout_id) == str(docs_layout.id)
        assert docs.content_json == _PORTAL_BODY

        sidebar = _sidebar_search_rows(db, docs)
        assert len(sidebar) == 1, "sidebar Search box not appended"
        nested = sidebar[0].config_override["config"]
        assert nested["quicksearch"] is True
        assert nested["scope"] == "both"
        assert nested["quicksearch_limit"] == 6


class TestDoesNotOverwriteExistingLayout:
    """The critical destructive-safety test: an operator-edited ``docs`` layout
    must survive the seed byte-for-byte (create-only, never update)."""

    _CUSTOM_AREAS = [
        {"name": "operator-area", "label": "Operator Area", "type": "content"}
    ]

    def test_does_NOT_overwrite_existing_layout(self, db):
        _seed_search_widgets()
        operator_layout = CmsLayout(
            slug="docs",
            name="OPERATOR CUSTOM DOCS",
            description="hand-edited by an operator",
            areas=self._CUSTOM_AREAS,
            sort_order=99,
            is_active=True,
        )
        db.session.add(operator_layout)
        db.session.commit()

        seed_docs_search()

        after = db.session.query(CmsLayout).filter_by(slug="docs").one()
        assert after.name == "OPERATOR CUSTOM DOCS", "layout name was overwritten"
        assert after.areas == self._CUSTOM_AREAS, "layout areas were overwritten"
        assert after.description == "hand-edited by an operator"
        assert after.sort_order == 99
        # And there is still exactly one docs layout (no duplicate created).
        assert db.session.query(CmsLayout).filter_by(slug="docs").count() == 1


class TestRepointPreservesExistingDocsWidgets:
    def test_repoint_preserves_existing_docs_widgets(self, db):
        _seed_search_widgets()
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        # Pre-attach an operator content widget to the docs page body.
        extra = _get_or_create_widget(
            "extra-doc-note",
            "Extra Doc Note",
            "html",
            content_html="<p>operator note</p>",
        )
        _ps, _ts, _pr, _tr, post_widget_repo = _build_unified_services()
        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        post_widget_repo.replace_for_post(
            str(docs.id),
            [
                {
                    "widget_id": str(extra.id),
                    "area_name": "content",
                    "sort_order": 0,
                    "config_override": None,
                }
            ],
        )
        db.session.commit()

        seed_docs_search()

        rows = post_widget_repo.find_by_post(str(docs.id))
        by_area: dict[str, list] = {}
        for row in rows:
            by_area.setdefault(row.area_name, []).append(row)
        # Operator content widget survived, sidebar Search added.
        assert len(by_area.get("content", [])) == 1, "operator widget was dropped"
        assert str(by_area["content"][0].widget_id) == str(extra.id)
        assert len(by_area.get("sidebar", [])) == 1, "sidebar Search not added"


class TestIdempotentSecondRunIsNoop:
    def test_idempotent_second_run_is_noop(self, db):
        _seed_search_widgets()
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        seed_docs_search()
        seed_docs_search()

        assert db.session.query(CmsLayout).filter_by(slug="docs").count() == 1
        assert db.session.query(CmsLayout).filter_by(slug="search").count() == 1
        assert (
            db.session.query(CmsPost).filter_by(type="page", slug="search").count() == 1
        )
        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        assert len(_sidebar_search_rows(db, docs)) == 1, "sidebar row duplicated"


class TestSkipsGracefullyWhenSearchWidgetAbsent:
    def test_skips_gracefully_when_search_widget_absent(self, db):
        # No search widget seeded.
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        # Must not raise.
        seed_docs_search()

        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        # /docs was NOT re-pointed (guarded by the missing search widget).
        assert docs.layout_id is None, "docs must not be re-pointed without search"
        assert len(_sidebar_search_rows(db, docs)) == 0, "no sidebar box expected"
        assert (
            db.session.query(CmsWidget).filter_by(slug="search").count() == 0
        ), "seed must not create the search widget"
