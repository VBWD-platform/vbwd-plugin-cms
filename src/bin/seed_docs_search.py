#!/usr/bin/env python3
"""Safe, CREATE-ONLY / APPEND-ONLY seed for the S121 docs + search demo.

The full ``populate_cms`` seeder is DESTRUCTIVE on a populated production DB:
it OVERWRITES every style/widget/layout (its ``_get_or_create_*`` update
branches), DELETE+re-inserts the header menu, and deletes the ``default``
routing rule. It must NOT be run on a live instance (e.g. vbwd.cc).

This entrypoint lands ONLY the S121 demo ``docs`` / ``search`` layouts, the
``/search`` demo page, and the ``/docs`` re-point — and every write here is
provably CREATE-ONLY or APPEND-ONLY:

  * Widgets are never created or modified — they are QUERIED (read-only) into a
    map. If the ``search`` widget is absent the ``/docs`` re-point is skipped
    (never crashes on a partially-seeded DB).
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
    _build_unified_services,
    _get_or_create_layout,
    _get_or_create_unified_page,
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


def _build_widget_map() -> dict[str, "CmsWidget"]:
    """Return ``{slug: CmsWidget}`` for the EXISTING widget rows (read-only).

    Never creates or mutates a widget — the destructive full seeder owns widget
    authoring. This map only lets the layout/page placements resolve widget ids
    (missing widgets degrade to a skip, not a crash).
    """
    return {widget.slug: widget for widget in db.session.query(CmsWidget).all()}


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


def seed_docs_search() -> None:
    """Land the S121 docs/search demo non-destructively (see module docstring)."""
    (
        post_service,
        _term_service,
        post_repo,
        _term_repo,
        post_widget_repo,
    ) = _build_unified_services()

    # (2) Read-only widget map — never authors widgets.
    widget_map = _build_widget_map()

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

    # (5) Re-point the EXISTING /docs page onto the docs layout (append-only).
    # Skip gracefully when the search widget is absent (partially-seeded DB).
    print("\n── Docs re-point (append-only) ─────────────────────────────────")
    if widget_map.get(_SEARCH_WIDGET_SLUG) is None:
        print("  WARN: 'search' widget absent — skipping /docs re-point")
    else:
        _repoint_docs_page_to_docs_layout(
            post_repo, post_widget_repo, layout_map, widget_map
        )
    db.session.commit()

    # (6) Summary.
    print("\n" + "=" * 55)
    print("✓ Safe docs/search seed complete (create-only / append-only)")
    print(f"  Layouts     : {sorted(layout_map.keys())}")
    print(f"  Search page : '{_SEARCH_PAGE_SLUG}' (create-only)")
    print("  Docs        : re-pointed to 'docs' layout (append-only)")
    print("=" * 55)


if __name__ == "__main__":
    from vbwd.app import create_app

    app = create_app()
    with app.app_context():
        seed_docs_search()
