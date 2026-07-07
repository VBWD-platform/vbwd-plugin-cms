"""Integration: the SAFE ``seed_docs_search`` entrypoint is non-destructive.

The full ``populate_cms`` seeder overwrites styles/widgets/layouts, DELETE+
re-inserts the header menu and deletes the ``default`` routing rule — so it can
never run on a live instance. ``seed_docs_search`` lands ONLY the S121 demo
``docs`` / ``search`` layouts, the ``/search`` page and the ``/docs`` re-point,
and every write is CREATE-ONLY or APPEND-ONLY. These tests are the safety proof:

  * it CREATES the demo layouts + re-points ``/docs`` when they are absent;
  * it CREATES the ``search`` / ``search-results`` widget records when absent
    (the prod scenario: those records only ever came from the destructive full
    seeder) and then re-points ``/docs``;
  * it NEVER overwrites an existing (operator-edited) ``docs`` layout;
  * it NEVER overwrites an existing (operator-edited) ``search`` widget;
  * the re-point preserves every pre-existing ``/docs`` widget;
  * a second run is a no-op (no duplicate layouts / pages / sidebar rows).

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


# Simulates an ALREADY-populated instance: a ``/search`` page whose
# ``search-results`` placement pre-dates the category fixture (stale, no
# ``mode``). The create-only page path leaves it as-is, so only the heal step
# can upgrade it — exactly the prod scenario S120 targets.
_STALE_RESULTS_OVERRIDE = {"config": {"scope": "both"}}


def _seed_preexisting_search_page_with_stale_results(db) -> CmsWidget:
    """Create a real ``/search`` page whose SearchResults placement carries a
    STALE (no-``mode``) override, returning the base ``search-results`` widget.

    The page is created THROUGH the unified service and the placement THROUGH the
    repo (never raw SQL), mirroring the state a live instance is in before S120.
    """
    post_service, _term, _post_repo, _tr, post_widget_repo = _build_unified_services()
    post_service.create_post(
        {
            "type": "page",
            "slug": "search",
            "title": "Search",
            "language": "en",
            "status": "published",
            "layout_id": None,
        }
    )
    results_widget = db.session.query(CmsWidget).filter_by(slug="search-results").one()
    search_page = db.session.query(CmsPost).filter_by(type="page", slug="search").one()
    post_widget_repo.replace_for_post(
        str(search_page.id),
        [
            {
                "widget_id": str(results_widget.id),
                "area_name": "results",
                "sort_order": 0,
                "config_override": dict(_STALE_RESULTS_OVERRIDE),
            }
        ],
    )
    return results_widget


def _results_placement_rows(db, search_page):
    return (
        db.session.query(CmsPostWidget)
        .filter_by(post_id=search_page.id, area_name="results")
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


class TestCreatesSearchWidgetsWhenAbsent:
    """The prod scenario that regressed: a live instance has the ``/docs`` page
    but NONE of the ``search`` / ``search-results`` widget records (those came
    only from the destructive full seeder we never run). The safe seed must
    CREATE them (create-only) and then complete the ``/docs`` re-point."""

    def test_creates_search_widgets_when_absent_then_repoints(self, db):
        # No search widgets seeded — exactly the failing prod state.
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        seed_docs_search()

        search_widget = db.session.query(CmsWidget).filter_by(slug="search").one()
        results_widget = (
            db.session.query(CmsWidget).filter_by(slug="search-results").one()
        )
        # S121 config defaults carried from _STANDALONE_VUE_WIDGETS (not re-coded).
        assert search_widget.config["scope"] == "both"
        assert search_widget.config["quicksearch"] is False
        assert search_widget.config["quicksearch_limit"] == 6
        assert search_widget.content_json == {"component": "Search"}
        assert results_widget.config["scope"] == "both"

        docs_layout = db.session.query(CmsLayout).filter_by(slug="docs").one()
        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        # /docs is now re-pointed onto the docs layout (the step that was skipped
        # on prod because the search widget was absent).
        assert str(docs.layout_id) == str(docs_layout.id)

        sidebar = _sidebar_search_rows(db, docs)
        assert len(sidebar) == 1, "sidebar Search box not appended"
        assert str(sidebar[0].widget_id) == str(search_widget.id)
        nested = sidebar[0].config_override["config"]
        assert nested["quicksearch"] is True
        assert nested["scope"] == "both"
        assert nested["quicksearch_limit"] == 6


class TestDoesNotOverwriteExistingSearchWidget:
    """The critical safety test: an operator-edited ``search`` widget must
    survive the seed byte-for-byte (create-only, never update) — the create
    path must run ONLY when the slug is absent."""

    _CUSTOM_CONFIG = {
        "component_name": "Search",
        "placeholder": "OPERATOR CUSTOM PLACEHOLDER",
        "scope": "pages",
        "quicksearch": True,
        "quicksearch_limit": 99,
    }
    _CUSTOM_CONTENT = {"component": "Search", "operator": "edited"}

    def test_does_NOT_overwrite_existing_search_widget(self, db):
        operator_widget = CmsWidget(
            slug="search",
            name="OPERATOR CUSTOM SEARCH",
            widget_type="vue-component",
            content_json=self._CUSTOM_CONTENT,
            config=self._CUSTOM_CONFIG,
            sort_order=0,
            is_active=True,
        )
        db.session.add(operator_widget)
        _seed_preexisting_docs_page(layout_id=None)
        db.session.commit()

        seed_docs_search()

        after = db.session.query(CmsWidget).filter_by(slug="search").one()
        assert after.config == self._CUSTOM_CONFIG, "search widget config overwritten"
        assert (
            after.content_json == self._CUSTOM_CONTENT
        ), "search widget content overwritten"
        assert after.name == "OPERATOR CUSTOM SEARCH", "search widget name overwritten"
        # Exactly one search widget (no duplicate created).
        assert db.session.query(CmsWidget).filter_by(slug="search").count() == 1

        # The re-point still proceeds and uses the EXISTING operator widget.
        docs = db.session.query(CmsPost).filter_by(type="page", slug="docs").one()
        docs_layout = db.session.query(CmsLayout).filter_by(slug="docs").one()
        assert str(docs.layout_id) == str(docs_layout.id)
        sidebar = _sidebar_search_rows(db, docs)
        assert len(sidebar) == 1
        assert str(sidebar[0].widget_id) == str(after.id)


class TestSearchResultsGetsCategoryOverride:
    """S120 — on an already-populated instance the ``/search`` page's
    SearchResults placement (stale, no ``mode``) must be healed to the
    WordPress-archive ``category`` card via a per-placement ``config_override``
    — the base widget config is left alone (a separate test proves that)."""

    def test_search_results_placement_gets_category_override(self, db):
        _seed_search_widgets()
        _seed_preexisting_search_page_with_stale_results(db)
        db.session.commit()

        seed_docs_search()

        search_page = (
            db.session.query(CmsPost).filter_by(type="page", slug="search").one()
        )
        results = _results_placement_rows(db, search_page)
        assert len(results) == 1, "SearchResults placement lost/duplicated"
        nested = results[0].config_override["config"]
        assert nested["mode"] == "category"
        assert nested["per_page"] == 8
        # The pre-existing override key survives the merge.
        assert nested["scope"] == "both"


class TestDoesNotOverwriteBaseSearchResultsWidgetConfig:
    """The critical safety test: the heal writes ONLY a per-placement override —
    the base ``search-results`` widget's ``config`` (which an operator may have
    customized) must survive byte-for-byte."""

    _CUSTOM_CONFIG = {
        "component_name": "SearchResults",
        "mode": "titles",
        "scope": "pages",
        "per_page": 25,
        "foo": "bar",
    }

    def test_does_NOT_overwrite_base_search_results_widget_config(self, db):
        operator_widget = CmsWidget(
            slug="search-results",
            name="OPERATOR CUSTOM RESULTS",
            widget_type="vue-component",
            content_json={"component": "SearchResults"},
            config=dict(self._CUSTOM_CONFIG),
            sort_order=0,
            is_active=True,
        )
        db.session.add(operator_widget)
        db.session.commit()
        _seed_preexisting_search_page_with_stale_results(db)
        db.session.commit()

        seed_docs_search()

        # BASE widget config is 100% untouched (only the placement carries mode).
        after = db.session.query(CmsWidget).filter_by(slug="search-results").one()
        assert after.config == self._CUSTOM_CONFIG, "base widget config overwritten"
        assert after.name == "OPERATOR CUSTOM RESULTS", "base widget name overwritten"
        assert db.session.query(CmsWidget).filter_by(slug="search-results").count() == 1

        # The placement (and only the placement) now carries category mode.
        search_page = (
            db.session.query(CmsPost).filter_by(type="page", slug="search").one()
        )
        results = _results_placement_rows(db, search_page)
        assert len(results) == 1
        assert results[0].config_override["config"]["mode"] == "category"


class TestSearchResultsModeHealIsIdempotent:
    def test_search_results_mode_heal_is_idempotent(self, db):
        _seed_search_widgets()
        _seed_preexisting_search_page_with_stale_results(db)
        db.session.commit()

        seed_docs_search()
        seed_docs_search()

        search_page = (
            db.session.query(CmsPost).filter_by(type="page", slug="search").one()
        )
        results = _results_placement_rows(db, search_page)
        assert len(results) == 1, "results placement duplicated on second run"
        assert results[0].config_override["config"]["mode"] == "category"
        # Exactly one /search page (no duplicate created by the second run).
        assert (
            db.session.query(CmsPost).filter_by(type="page", slug="search").count() == 1
        )
