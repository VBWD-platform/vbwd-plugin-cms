#!/usr/bin/env python3
"""Safe, CREATE-ONLY / APPEND-ONLY seed for the S121 docs + search demo.

The full ``populate_cms`` seeder is DESTRUCTIVE on a populated production DB:
it OVERWRITES every style/widget/layout (its ``_get_or_create_*`` update
branches), DELETE+re-inserts the header menu, and deletes the ``default``
routing rule. It must NOT be run on a live instance (e.g. vbwd.cc).

This entrypoint lands ONLY the S121 demo ``docs`` / ``search`` layouts, the
``/search`` demo page, and the ``/docs`` re-point — and every write here is
provably CREATE-ONLY or APPEND-ONLY:

  * Widgets are CREATE-ONLY: the map starts from the EXISTING widget rows
    (read-only), and the ``search`` / ``search-results`` records are created
    ONLY when their slug is absent (their canonical S121 config comes from
    ``populate_cms._STANDALONE_VUE_WIDGETS`` — DRY). An existing (operator-edited)
    widget is LEFT 100% UNTOUCHED (we never reach the overwrite branch of
    ``_get_or_create_widget``). This is what lets the ``/docs`` re-point complete
    on a production instance that never ran the destructive full seeder.
  * Layouts are created ONLY when absent. An existing ``docs`` / ``search``
    layout is LEFT UNTOUCHED (``_create_layout_if_absent`` never reaches the
    overwrite branch of ``_get_or_create_layout``).
  * The ``/search`` page goes through the create-only page path
    (``_get_or_create_unified_page``), which resolves — never overwrites — an
    existing page on a slug conflict.
  * The ``/docs`` re-point reuses the unchanged, append-only
    ``_repoint_docs_page_to_docs_layout`` (changes only ``layout_id`` + appends
    the sidebar Search box; preserves body/SEO/all other widgets; idempotent).

DRY: every piece of behaviour is imported from ``populate_cms`` — this module
adds only the create-only layout guard and the narrow orchestration.

Engineering requirements (binding, restated): TDD-first (safety proven by the
create-only / repoint-preserving tests); DevOps-first (real PG, cold local + CI;
seeded through services/repos, never raw SQL); SOLID/DI/DRY (one home per
behaviour — reused from populate_cms); Liskov (a missing widget degrades to a
skip, never a false success); clean code; NO OVERENGINEERING (the narrowest
non-destructive slice). Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.

Usage:
    python /app/plugins/cms/src/bin/seed_docs_search.py
"""
import sys
from pathlib import Path
from typing import Optional, cast

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from vbwd.extensions import db  # noqa: E402
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.bin.populate_cms import (  # noqa: E402
    _STANDALONE_VUE_WIDGETS,
    _build_unified_services,
    _get_or_create_layout,
    _get_or_create_unified_page,
    _get_or_create_widget,
    _load_layouts,
    _load_pages,
    _repoint_docs_page_to_docs_layout,
    _set_unified_page_widgets,
)

# The two demo layouts and the one demo page this safe seed is allowed to land.
_DOCS_SEARCH_LAYOUT_SLUGS = ("docs", "search")
_SEARCH_PAGE_SLUG = "search"
# The widget whose presence gates the /docs re-point (the sidebar quicksearch).
_SEARCH_WIDGET_SLUG = "search"
# The Search widget records this safe seed is allowed to CREATE (only if absent).
# Their canonical S121 config defaults live in ``_STANDALONE_VUE_WIDGETS`` — we
# reference (never re-hardcode) them so created rows match the full seeder.
_SEARCH_WIDGET_SLUGS = ("search", "search-results")
_DOCS_PAGE_SLUG = "docs"
_DOCS_LAYOUT_SLUG = "docs"

# S120 — the /search page's SearchResults placement must render in the
# WordPress-archive ``category`` card on ALL instances (including already-
# populated prod). The base ``search-results`` widget config is NEVER touched
# (operators may have customized it); instead a per-placement ``config_override``
# — which the fe-user renderer merges over the base config under ``config`` —
# carries the category mode. These name the results placement to heal.
_SEARCH_RESULTS_WIDGET_SLUG = "search-results"
_SEARCH_RESULTS_AREA = "results"
_SEARCH_RESULTS_CATEGORY_MODE = "category"
_SEARCH_RESULTS_PER_PAGE = 8


def _build_widget_map() -> dict[str, "CmsWidget"]:
    """Return ``{slug: CmsWidget}`` for the EXISTING widget rows (read-only).

    Never mutates a widget — this map only lets the layout/page placements and
    the ``/docs`` re-point resolve widget ids. The Search widget records are then
    ensured create-only on top of it (see ``_ensure_search_widget_if_absent``).
    """
    return {widget.slug: widget for widget in db.session.query(CmsWidget).all()}


def _canonical_search_widget_definitions() -> list[dict]:
    """The canonical ``search`` / ``search-results`` definitions, referenced
    (DRY) from ``populate_cms._STANDALONE_VUE_WIDGETS`` so any created record
    carries the S121 config defaults (scope ``both``, quicksearch off, limit 6)."""
    return [
        definition
        for definition in _STANDALONE_VUE_WIDGETS
        if definition["slug"] in _SEARCH_WIDGET_SLUGS
    ]


def _ensure_search_widget_if_absent(definition: dict) -> "CmsWidget":
    """Create a Search widget record ONLY when its slug is absent; otherwise
    return the EXISTING row 100% untouched.

    CRITICAL (destructive-safety): ``_get_or_create_widget`` OVERWRITES an
    existing widget's ``name`` / ``content_json`` / ``source_css`` / ``config``
    in its ``if existing:`` branch. An operator may have edited the Search box,
    so we must never reach that branch for an existing slug — we short-circuit on
    an existing row and delegate to the seeder's helper (reaching solely its
    CREATE branch) only when the slug is genuinely absent. DRY: the S121 config
    defaults come from the referenced ``_STANDALONE_VUE_WIDGETS`` definition.
    """
    slug = definition["slug"]
    existing = db.session.query(CmsWidget).filter_by(slug=slug).first()
    if existing is not None:
        print(f"  ~ widget '{slug}' exists — left as-is")
        return existing
    return _get_or_create_widget(
        definition["slug"],
        definition["name"],
        definition["widget_type"],
        content_json=definition.get("content_json"),
        config=definition.get("config"),
    )


def _create_layout_if_absent(data: dict, widget_map: dict) -> "CmsLayout":
    """Create a layout ONLY when its slug is absent; otherwise leave it as-is.

    CRITICAL (destructive-safety): ``_get_or_create_layout`` OVERWRITES an
    existing layout's ``name`` / ``areas`` / ``description`` in its ``if
    existing:`` branch. We must never do that to an operator-edited layout, so
    we short-circuit on an existing row and only delegate to the full seeder's
    helper (reaching solely its create branch) when the slug is genuinely
    absent. DRY: the widget-assignment create logic is not duplicated here.
    """
    slug = data["slug"]
    existing = db.session.query(CmsLayout).filter_by(slug=slug).first()
    if existing is not None:
        print(f"  ~ layout '{slug}' exists — left as-is")
        return existing
    return _get_or_create_layout(data, widget_map)


def _ensure_search_results_category_mode(
    post_repo, post_widget_repo, widget_map
) -> str:
    """Idempotently ensure the ``/search`` page's SearchResults placement renders
    in the WordPress-archive ``category`` card via a per-placement
    ``config_override`` — WITHOUT ever overwriting the base ``search-results``
    widget's ``config`` (an operator may have customized it).

    Narrow, append-only and non-destructive (mirrors
    ``_repoint_docs_page_to_docs_layout``): it preserves every OTHER placement and
    every OTHER override key, and on the results placement it only sets
    ``config.mode == 'category'`` (+ ``per_page``), merged over whatever the
    override already carries (e.g. ``scope``). A re-run — where the override is
    already ``category`` — is a no-op (no rewrite, no duplicate placement). It
    NEVER queries or mutates a ``CmsWidget`` row, so the base widget config is
    structurally out of reach here.

    Returns a human-readable outcome for the summary. Degrades to a skip (never a
    false success) when the ``/search`` page, the ``search-results`` widget, or
    the results placement is absent.
    """
    search_page = post_repo.find_by_type_and_slug("page", _SEARCH_PAGE_SLUG)
    results_widget = widget_map.get(_SEARCH_RESULTS_WIDGET_SLUG)
    if search_page is None or results_widget is None:
        return "skipped ('/search' page or 'search-results' widget unavailable)"

    existing = post_widget_repo.find_by_post(str(search_page.id))

    def _is_results_placement(row) -> bool:
        return (
            str(row.widget_id) == str(results_widget.id)
            and row.area_name == _SEARCH_RESULTS_AREA
        )

    def _is_category(override) -> bool:
        return (
            isinstance(override, dict)
            and isinstance(override.get("config"), dict)
            and override["config"].get("mode") == _SEARCH_RESULTS_CATEGORY_MODE
        )

    results_rows = [row for row in existing if _is_results_placement(row)]
    if not results_rows:
        return "skipped (no SearchResults placement on '/search')"
    # Idempotent: a results placement already in category mode needs no change.
    if all(_is_category(row.config_override) for row in results_rows):
        return "already 'category' mode"

    # Preserve every existing placement; on the results placement, MERGE the
    # category mode over the existing nested override (keeping e.g. ``scope``).
    rows: list[dict] = []
    for row in existing:
        override = row.config_override
        if _is_results_placement(row) and not _is_category(override):
            nested = (
                dict(override["config"])
                if isinstance(override, dict)
                and isinstance(override.get("config"), dict)
                else {}
            )
            nested["mode"] = _SEARCH_RESULTS_CATEGORY_MODE
            nested["per_page"] = _SEARCH_RESULTS_PER_PAGE
            override = {"config": nested}
        rows.append(
            {
                "widget_id": str(row.widget_id),
                "area_name": row.area_name,
                "sort_order": row.sort_order,
                "required_access_level_ids": row.required_access_level_ids,
                "config_override": override,
            }
        )
    post_widget_repo.replace_for_post(str(search_page.id), rows)
    return "SearchResults set to 'category' mode (per-placement override)"


def seed_docs_search() -> None:
    """Land the S121 docs/search demo non-destructively (see module docstring)."""
    (
        post_service,
        _term_service,
        post_repo,
        _term_repo,
        post_widget_repo,
    ) = _build_unified_services()

    # (2) Widget map: start from the EXISTING rows (read-only), then ensure the
    # Search widgets create-only-if-absent. On a prod instance these records
    # never existed (only the destructive full seeder creates them), which is why
    # the /docs re-point and the search-page wiring silently no-oped before.
    widget_map = _build_widget_map()
    print("\n── Search widgets (create-only-if-absent) ──────────────────────")
    for widget_definition in _canonical_search_widget_definitions():
        ensured_widget = _ensure_search_widget_if_absent(widget_definition)
        widget_map[ensured_widget.slug] = ensured_widget
    db.session.commit()

    # (3) Create the docs + search demo layouts ONLY IF ABSENT; build a
    # layout_map (slug → CmsLayout) from the existing-or-created rows.
    print("\n── Layouts (docs, search — create-only) ────────────────────────")
    layout_map: dict[str, "CmsLayout"] = {}
    for layout_row in _load_layouts():
        layout_slug = cast(str, layout_row.get("slug"))
        if layout_slug in _DOCS_SEARCH_LAYOUT_SLUGS:
            layout_map[layout_slug] = _create_layout_if_absent(layout_row, widget_map)
    db.session.commit()

    # (4) Create the /search demo page ONLY IF ABSENT (create-only page path),
    # then wire its box + results page-widgets from the fixture.
    print("\n── Search page (create-only) ───────────────────────────────────")
    for page_row in _load_pages():
        if page_row.get("slug") != _SEARCH_PAGE_SLUG:
            continue
        page_layout_slug = cast(Optional[str], page_row.get("layout_slug"))
        layout_obj = layout_map.get(page_layout_slug) if page_layout_slug else None
        post = _get_or_create_unified_page(
            post_service,
            post_repo,
            page_row["slug"],
            page_row["name"],
            layout_obj,
            None,
            content_json=page_row.get("content_json"),
            content_html=page_row.get("content_html"),
            meta_description=page_row.get("meta_description"),
            sort_order=page_row.get("sort_order", 0),
            robots=page_row.get("robots", "index,follow"),
            is_published=page_row.get("is_published", True),
        )
        assignments = page_row.get("page_widget_assignments", [])
        if post and assignments:
            _set_unified_page_widgets(post_widget_repo, post, assignments, widget_map)
    db.session.commit()

    # (4b) Heal the /search page's SearchResults placement to the category card
    # on ALREADY-populated instances (where the page + placement pre-date the
    # category fixture, so step (4) skipped its per-page widgets). Append-only,
    # idempotent, and it NEVER touches the base widget config.
    print("\n── Search results category mode (append-only heal) ─────────────")
    search_results_outcome = _ensure_search_results_category_mode(
        post_repo, post_widget_repo, widget_map
    )
    print(f"  {search_results_outcome}")
    db.session.commit()

    # (5) Re-point the EXISTING /docs page onto the docs layout (append-only).
    # Track the ACTUAL outcome so the summary reports it truthfully.
    print("\n── Docs re-point (append-only) ─────────────────────────────────")
    docs_page = post_repo.find_by_type_and_slug("page", _DOCS_PAGE_SLUG)
    docs_layout = layout_map.get(_DOCS_LAYOUT_SLUG)
    if docs_page is None:
        docs_outcome = "skipped (no /docs page present)"
        print("  ~ no /docs page present — nothing to re-point")
    elif widget_map.get(_SEARCH_WIDGET_SLUG) is None or docs_layout is None:
        docs_outcome = "skipped ('search' widget or 'docs' layout unavailable)"
        print("  WARN: 'search' widget or 'docs' layout unavailable — skipping")
    else:
        already_correct = str(docs_page.layout_id) == str(docs_layout.id)
        _repoint_docs_page_to_docs_layout(
            post_repo, post_widget_repo, layout_map, widget_map
        )
        docs_outcome = (
            "already on 'docs' layout"
            if already_correct
            else "re-pointed to 'docs' layout (append-only)"
        )
    db.session.commit()

    # (6) Summary — reports the ACTUAL outcome, not an optimistic constant.
    print("\n" + "=" * 55)
    print("✓ Safe docs/search seed complete (create-only / append-only)")
    print(f"  Layouts       : {sorted(layout_map.keys())}")
    print(f"  Search page   : '{_SEARCH_PAGE_SLUG}' (create-only)")
    print(f"  Search results: {search_results_outcome}")
    print(f"  Docs          : {docs_outcome}")
    print("=" * 55)


if __name__ == "__main__":
    from vbwd.app import create_app

    app = create_app()
    with app.app_context():
        seed_docs_search()
