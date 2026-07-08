"""Unit tests for populate_cms's envelope-aware demo loaders.

The demo import files under ``docs/imports/{theme-styles.json,layouts/,pages/}``
were converted to S46 export envelopes (``{"vbwd_export": <key>, "version": 1,
"<key>": [rows]}``) with translated field names (``title``, ``status``,
``terms``, ``page_assignments``). The seeder reads those files *directly* (it
does not go through the import service), so its loaders must unwrap the envelope
and translate the field names back to the bare shape its helpers expect.

These tests read the REAL converted fixture files (not just fakes) for the
envelope-unwrap + field-translate path so the regression cannot silently recur.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI, no DB needed here); SOLID/DI/DRY (one unwrap home reused by every
loader); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin import populate_cms


class TestEnvelopeUnwrap:
    def test_unwrap_returns_rows_under_entity_key(self):
        envelope = {"vbwd_export": "cms_styles", "version": 1, "cms_styles": [{"a": 1}]}
        assert populate_cms._unwrap_envelope(envelope, "cms_styles") == [{"a": 1}]

    def test_unwrap_tolerates_bare_list(self):
        assert populate_cms._unwrap_envelope([{"a": 1}], "cms_styles") == [{"a": 1}]

    def test_unwrap_missing_key_yields_empty(self):
        assert populate_cms._unwrap_envelope({"other": []}, "cms_styles") == []


class TestThemeStylesLoader:
    def test_styles_loaded_from_envelope(self):
        styles, default_slug = populate_cms._load_theme_styles()
        assert len(styles) > 0
        # Real style rows carry slug + source_css.
        assert all("slug" in style and "source_css" in style for style in styles)
        assert default_slug


class TestLayoutLoader:
    def test_layouts_loaded_and_carry_placements(self):
        layouts = populate_cms._load_layouts()
        assert len(layouts) > 0
        by_slug = {layout["slug"]: layout for layout in layouts}
        # Every layout row carries the seeder-owned widget_assignments key.
        assert all("widget_assignments" in layout for layout in layouts)
        # content-page is seeded with header/breadcrumbs/footer placements.
        content_page = by_slug["content-page"]
        placed_widgets = {
            widget for _area, widget in content_page["widget_assignments"]
        }
        assert "header-nav" in placed_widgets
        assert "footer-nav" in placed_widgets
        # The global analytics widget is NOT a layout placement — it renders
        # site-wide via GET /cms/widgets/global.
        assert "custom-code-analytics" not in placed_widgets

    def test_placement_widget_slugs_exist_in_widget_map(self):
        """Every placed widget slug must be one the seeder actually creates."""
        placed = {
            widget
            for placements in populate_cms._LAYOUT_WIDGET_PLACEMENTS.values()
            for _area, widget in placements
        }
        seeded_widget_slugs = {
            "header-nav",
            "footer-nav",
            "breadcrumbs",
            "contact-form",
            "ghrm-categories",
            "ghrm-software-detail",
            "hero-home1",
            "hero-home2",
            "features-3col",
            "cta-primary",
            "pricing-2col",
            "testimonials",
            "pricing-native-plans",
            "tag-archive",
            "posts-archive",
            "addon-catalog",
            "cookie-consent",
        }
        assert placed <= seeded_widget_slugs


class TestPageLoader:
    def test_pages_loaded_with_translated_fields(self):
        pages = populate_cms._load_pages()
        assert len(pages) > 0
        by_slug = {page["slug"]: page for page in pages}
        # title → name.
        about = by_slug["about"]
        assert about["name"] == "About Us"
        # status → is_published.
        assert about["is_published"] is True
        # terms (category) → category_slug.
        assert about["category_slug"] == "about"
        # page_assignments → page_widget_assignments (preserved shape).
        assert about["page_widget_assignments"][0]["widget_slug"] == "testimonials"

    def test_draft_status_translates_to_unpublished(self):
        pages = populate_cms._load_pages()
        by_slug = {page["slug"]: page for page in pages}
        draft = by_slug["ghrm-software-catalogue"]
        assert draft["is_published"] is False


class TestVerticalLandingPages:
    """The three public vertical landing pages (/tarifs, /soft, /addons) are
    seeded as published CMS layout pages. /tarifs and /soft REUSE existing
    layouts (no duplicate layouts); only /addons introduces a new layout that
    hosts the new AddonCatalog widget."""

    def test_three_landing_pages_seeded_and_published(self):
        pages = populate_cms._load_pages()
        by_slug = {page["slug"]: page for page in pages}
        # /tarifs and /soft reuse existing layouts; /addons has its own.
        for slug, layout_slug in (
            ("tarifs", "native-pricing-page"),
            ("soft", "ghrm-software-catalogue"),
            ("addons", "addons"),
        ):
            assert slug in by_slug, f"page '{slug}' not seeded"
            page = by_slug[slug]
            assert page["is_published"] is True
            assert page["layout_slug"] == layout_slug

    def test_landing_page_layouts_host_the_expected_catalog_widget(self):
        # Each landing page's layout (reused or new) places its catalog widget.
        placements = populate_cms._LAYOUT_WIDGET_PLACEMENTS
        for layout_slug, expected_widget in (
            ("native-pricing-page", "pricing-native-plans"),
            ("ghrm-software-catalogue", "ghrm-categories"),
            ("addons", "addon-catalog"),
        ):
            assert layout_slug in placements, f"layout '{layout_slug}' missing"
            placed_widgets = {widget for _area, widget in placements[layout_slug]}
            assert expected_widget in placed_widgets

    def test_only_addons_introduces_a_new_layout_import(self):
        # /tarifs and /soft must NOT ship duplicate layout import files.
        layouts = populate_cms._load_layouts()
        by_slug = {layout["slug"]: layout for layout in layouts}
        assert "addons" in by_slug
        assert by_slug["addons"]["is_active"] is True
        assert "tarifs" not in by_slug, "duplicate /tarifs layout should not exist"
        assert "soft" not in by_slug, "duplicate /soft layout should not exist"


class TestLostStandaloneWidgets:
    """The CustomCode / Category / Search / SearchResults vue-component widgets
    are registered in fe-user and have fe-admin editor descriptors, but had no
    seeded widget RECORD — so they never appeared in the admin widget picker
    (which lists widget records from the DB). The seeder now creates a
    standalone record for each, driven by ``_STANDALONE_VUE_WIDGETS`` so the
    set is a single source of truth and unit-testable without a DB."""

    def test_lost_widgets_are_defined(self):
        by_slug = {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}
        for slug in ("code-snippet", "category", "search", "search-results"):
            assert slug in by_slug, f"standalone widget '{slug}' not defined"

    def test_each_standalone_widget_is_a_vue_component_with_its_name(self):
        expected_component = {
            "code-snippet": "CustomCode",
            "category": "Category",
            "search": "Search",
            "search-results": "SearchResults",
        }
        by_slug = {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}
        for slug, component in expected_component.items():
            widget = by_slug[slug]
            assert widget["widget_type"] == "vue-component"
            assert widget["content_json"]["component"] == component
            assert widget["name"]

    def test_code_snippet_carries_a_demo_custom_code_config(self):
        by_slug = {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}
        config = by_slug["code-snippet"]["config"]
        assert config["component_name"] == "CustomCode"
        # The demo ships a placeholder <script>/HTML block (counters, analytics).
        assert "code" in config


class TestSearchWidgetScopeConfig:
    """S121 — the seeded ``search`` / ``search-results`` widget records carry a
    constrained ``scope`` (``pages`` | ``posts`` | ``both``) plus the quicksearch
    controls, replacing the legacy free-text ``type`` on SearchResults. Config is
    the single source of truth (matches the fe-admin editor defaults); asserted
    without a DB so drift is caught at unit speed."""

    def _by_slug(self):
        return {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}

    def test_search_box_config_carries_scope_and_quicksearch_defaults(self):
        config = self._by_slug()["search"]["config"]
        # Existing keys are preserved.
        assert config["component_name"] == "Search"
        assert config["placeholder"] == "Search…"
        assert config["target_path"] == ""
        # New S121 keys with their defaults.
        assert config["scope"] == "both"
        assert config["quicksearch"] is False
        assert config["quicksearch_limit"] == 6

    def test_search_results_config_replaces_type_with_scope(self):
        config = self._by_slug()["search-results"]["config"]
        # Existing keys are preserved.
        assert config["component_name"] == "SearchResults"
        # S120 — a fresh install defaults the results to the WordPress-archive
        # ``category`` card (was ``titles``); per_page tightened to 8.
        assert config["mode"] == "category"
        assert config["per_page"] == 8
        # ``type`` is replaced by the constrained ``scope`` (default ``both``).
        assert "type" not in config
        assert config["scope"] == "both"

    def test_search_results_default_mode_is_category(self):
        # S120 — the fresh-install SearchResults renders the category archive
        # card by default (fe-user SearchResults ``mode: 'category'``).
        config = self._by_slug()["search-results"]["config"]
        assert config["mode"] == "category"


class TestSearchResultsDocsWidget:
    """A SECOND SearchResults record — ``search-results-docs`` — ships so a
    docs/pages-scoped search-results widget appears in the admin picker on every
    install. It reuses the same ``SearchResults`` vue component as the general
    ``search-results`` record but scopes the query to pages only
    (``types: ['page']``) in WordPress-archive ``category`` mode. Config is the
    single source of truth (``_STANDALONE_VUE_WIDGETS``); asserted without a DB
    so drift is caught at unit speed."""

    def _by_slug(self):
        return {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}

    def test_search_results_docs_record_is_defined(self):
        assert (
            "search-results-docs" in self._by_slug()
        ), "docs-scoped search-results record not defined"

    def test_search_results_docs_is_a_searchresults_vue_component(self):
        widget = self._by_slug()["search-results-docs"]
        assert widget["widget_type"] == "vue-component"
        assert widget["content_json"]["component"] == "SearchResults"
        assert widget["name"] == "Search Results — Docs"

    def test_search_results_docs_config_is_pages_scoped_category_mode(self):
        config = self._by_slug()["search-results-docs"]["config"]
        assert config["component_name"] == "SearchResults"
        # Docs split: pages-only scope (the general ``search-results`` record
        # covers post+page); category card; 8 per page.
        assert config["types"] == ["page"]
        assert config["mode"] == "category"
        assert config["per_page"] == 8

    def test_general_search_results_record_stays_content_scoped(self):
        # The pre-existing general record is untouched by the docs split — it
        # remains the broad content search (its own scope key), distinct from
        # the new pages-only docs record.
        by_slug = self._by_slug()
        assert "search-results" in by_slug
        assert by_slug["search-results"]["config"]["component_name"] == "SearchResults"
        assert by_slug["search-results-docs"] is not by_slug["search-results"]


class TestCatalogCollectionWidgets:
    """Two pure-frontend catalog widgets — TariffPlanCollection and
    TokenBundleCollection — are seeded as standalone vue-component RECORDS so
    they appear in the admin widget picker and can be placed on CMS pages.
    They consume EXISTING public catalog APIs (``GET /tarif-plans?category=…``
    / ``GET /tarif-plans/<slug>`` and ``GET /token-bundles/``); the seeds add
    no backend endpoints — only the picker records. Driven by
    ``_STANDALONE_VUE_WIDGETS`` so the set stays a single source of truth and
    is unit-testable without a DB."""

    def _by_slug(self):
        return {w["slug"]: w for w in populate_cms._STANDALONE_VUE_WIDGETS}

    def test_collection_widgets_are_defined(self):
        by_slug = self._by_slug()
        for slug in ("tariff-plan-collection", "token-bundle-collection"):
            assert slug in by_slug, f"collection widget '{slug}' not defined"

    def test_each_collection_widget_is_a_vue_component_with_its_name(self):
        expected_component = {
            "tariff-plan-collection": "TariffPlanCollection",
            "token-bundle-collection": "TokenBundleCollection",
        }
        by_slug = self._by_slug()
        for slug, component in expected_component.items():
            widget = by_slug[slug]
            assert widget["widget_type"] == "vue-component"
            assert widget["content_json"]["component"] == component
            assert widget["name"]

    def test_tariff_plan_collection_config_keys(self):
        config = self._by_slug()["tariff-plan-collection"]["config"]
        assert config["component_name"] == "TariffPlanCollection"
        assert config["source_mode"] == "category"
        assert config["category"] == "root"
        assert config["plan_slugs"] == []
        assert config["default_view"] == "cards"
        assert config["heading"] == ""

    def test_token_bundle_collection_config_keys(self):
        config = self._by_slug()["token-bundle-collection"]["config"]
        assert config["component_name"] == "TokenBundleCollection"
        assert config["bundle_ids"] == []
        assert config["default_view"] == "cards"
        assert config["heading"] == ""


class TestPageWidgetDemo:
    """A layout declares a ``page-widget`` slot (an AREA, type 'page-widget');
    each page picks the concrete widget for that slot via ``page_assignments``.
    The demo proves the feature end-to-end: the layout's area + the page's
    assignment to it."""

    def _demo_layout(self):
        layouts = populate_cms._load_layouts()
        by_slug = {layout["slug"]: layout for layout in layouts}
        assert "page-widget-demo" in by_slug, "page-widget demo layout not seeded"
        return by_slug["page-widget-demo"]

    def test_demo_layout_declares_a_page_widget_area(self):
        layout = self._demo_layout()
        area_types = {area["type"] for area in layout["areas"]}
        assert "page-widget" in area_types
        # The slot's area name is referenced by the demo page's assignment.
        page_widget_areas = [
            area["name"] for area in layout["areas"] if area["type"] == "page-widget"
        ]
        assert "sidebar" in page_widget_areas

    def test_demo_page_assigns_a_widget_to_the_page_widget_slot(self):
        pages = populate_cms._load_pages()
        by_slug = {page["slug"]: page for page in pages}
        assert "page-widget-demo" in by_slug, "page-widget demo page not seeded"
        page = by_slug["page-widget-demo"]
        assert page["layout_slug"] == "page-widget-demo"
        assignments = page["page_widget_assignments"]
        assert len(assignments) >= 1
        sidebar = next(a for a in assignments if a["area_name"] == "sidebar")
        # The page fills the slot with a concrete widget the seeder creates.
        # Assert it's one of the seeded standalone widgets (drift-proof) rather
        # than a hardcoded slug — the demo's chosen widget is a CMS content
        # decision, not this test's contract.
        standalone_slugs = {w["slug"] for w in populate_cms._STANDALONE_VUE_WIDGETS}
        assert sidebar["widget_slug"] in standalone_slugs

    def test_demo_page_assigned_widget_is_seeded(self):
        pages = populate_cms._load_pages()
        page = {p["slug"]: p for p in pages}["page-widget-demo"]
        sidebar = next(
            a for a in page["page_widget_assignments"] if a["area_name"] == "sidebar"
        )
        standalone_slugs = {w["slug"] for w in populate_cms._STANDALONE_VUE_WIDGETS}
        assert sidebar["widget_slug"] in standalone_slugs


class TestSearchDemoLayouts:
    """S121 §4.5 — two demo layouts ship so a fresh install shows both search
    journeys as *data*, not code:

      - ``docs``   — a self-contained quicksearch box in a sidebar slot
        (``config_override`` turns quicksearch on).
      - ``search`` — the classic box (``target_path=/search``) + a
        ``SearchResults`` widget in a results slot.

    Loader tests read the REAL fixture files (no DB) so the seeded layouts, the
    area→widget assignments, and the ``config_override`` cannot silently drift.
    """

    def _layouts_by_slug(self):
        return {layout["slug"]: layout for layout in populate_cms._load_layouts()}

    def _pages_by_slug(self):
        return {page["slug"]: page for page in populate_cms._load_pages()}

    def _assignment(self, page, area_name):
        return next(
            a for a in page["page_widget_assignments"] if a["area_name"] == area_name
        )

    def test_docs_layout_seeded_with_page_widget_slot(self):
        docs = self._layouts_by_slug()["docs"]
        assert docs["name"] == "Docs pages"
        area_types = {area["type"] for area in docs["areas"]}
        # A page-widget slot hosts the Search box; a content area holds the body.
        assert "page-widget" in area_types
        assert "content" in area_types

    def test_docs_page_assigns_search_box_with_quicksearch_override(self):
        docs_page = self._pages_by_slug()["docs"]
        assert docs_page["layout_slug"] == "docs"
        sidebar = self._assignment(docs_page, "sidebar")
        assert sidebar["widget_slug"] == "search"
        # The demo turns quicksearch ON via a per-placement config_override.
        # Defect 1 — vue-component widget overrides MUST be nested under
        # ``config`` (the fe-user renderer merges ``override.config`` into the
        # widget config); a FLAT override is silently ignored.
        override = sidebar["config_override"]
        assert "quicksearch" not in override, "override must be nested under 'config'"
        nested = override["config"]
        assert nested["quicksearch"] is True
        assert nested["scope"] == "both"
        assert nested["quicksearch_limit"] == 6

    def test_search_layout_seeded_with_box_and_results_slots(self):
        search = self._layouts_by_slug()["search"]
        assert search["name"] == "Search"
        area_names = {area["name"] for area in search["areas"]}
        assert "search" in area_names
        assert "results" in area_names

    def test_search_page_wires_box_targetpath_and_results_widget(self):
        search_page = self._pages_by_slug()["search"]
        assert search_page["layout_slug"] == "search"
        box = self._assignment(search_page, "search")
        assert box["widget_slug"] == "search"
        # The classic box navigates to the /search results page. Defect 1 —
        # vue-component overrides are nested under ``config``.
        assert box["config_override"]["config"]["target_path"] == "/search"
        assert box["config_override"]["config"]["scope"] == "both"
        results = self._assignment(search_page, "results")
        assert results["widget_slug"] == "search-results"
        # S120 — the results placement carries a per-placement override that
        # switches the SearchResults card to WordPress-archive ``category`` mode
        # (nested under ``config`` so the fe-user renderer merges it).
        assert results["config_override"]["config"]["mode"] == "category"
        assert results["config_override"]["config"]["per_page"] == 8
