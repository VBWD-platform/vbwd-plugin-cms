#!/usr/bin/env python3
"""Install the shared ``terms-archive`` CMS layout onto an existing database.

Deploy runs the destructive ``populate_cms.py`` seeders on NO instance (they
would overwrite operator content), so the ``terms-archive`` layout (and its
route-driven ``TermArchive`` widget) never reaches an already-provisioned
database that way. On prod that makes ``GET /cms/layouts/by-slug/terms-archive``
return 404, and EVERY archive page — the WordPress-style prefix archives
(``/blog/2026``, ``/blog/2026/vbwd``) and the existing category/tag archives
(``/category/*``, ``/tag/*``) — renders degraded, because the fe-user store binds
those synthetic archive pages to the ``terms-archive`` layout. This applier is
the safe counterpart, in the exact mould of ``apply_cms_pages.py`` /
``apply_super_header.py`` / ``apply_pricing_card_defaults.py``.

CREATE-ONLY / non-destructive, fully idempotent:

* Widget — if the ``terms-archive`` widget is ABSENT it is created from the
  canonical ``populate_cms`` definition (so applier and seeder can never drift).
  If it is already PRESENT it is left completely untouched.
* Layout — if the ``terms-archive`` layout is ABSENT it is created from the
  canonical bundled layout row (its ``header``/``breadcrumbs``/``archive``/
  ``footer`` areas), and each seeder-owned widget placement whose widget exists
  is assigned (the ``archive`` area → the TermArchive widget). If the layout is
  already PRESENT it is left completely untouched — an operator may have
  customised it.

A second run creates nothing and never duplicates the layout/widget/areas/
assignments.

Usage (matches how deploy invokes it):
    docker-compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python plugins/cms/src/bin/apply_terms_archive_layout.py'
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from plugins.cms.src.bin import populate_cms  # noqa: E402
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.repositories.cms_layout_repository import (  # noqa: E402
    CmsLayoutRepository,
)
from plugins.cms.src.repositories.cms_layout_widget_repository import (  # noqa: E402
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import (  # noqa: E402
    CmsWidgetRepository,
)

_STATUS_CREATED = "created"
_STATUS_ALREADY_PRESENT = "already-present"


class TermsArchiveApplyError(Exception):
    """Raised when the terms-archive layout cannot be created."""


def _ensure_terms_archive_widget(
    widget_repo: CmsWidgetRepository,
) -> Tuple[CmsWidget, str]:
    """Create the ``terms-archive`` widget CREATE-ONLY. Returns (widget, status).

    Sourced from ``populate_cms``'s canonical definition so the applier and the
    seeder can never drift. An existing widget is returned untouched.
    """
    existing = widget_repo.find_by_slug(populate_cms.TERMS_ARCHIVE_WIDGET_SLUG)
    if existing is not None:
        return existing, _STATUS_ALREADY_PRESENT

    widget = CmsWidget(
        slug=populate_cms.TERMS_ARCHIVE_WIDGET_SLUG,
        name=populate_cms.TERMS_ARCHIVE_WIDGET_NAME,
        widget_type="vue-component",
        content_json=dict(populate_cms.TERMS_ARCHIVE_WIDGET_CONTENT_JSON),
        config=dict(populate_cms.TERMS_ARCHIVE_WIDGET_CONFIG),
        sort_order=0,
        is_active=True,
    )
    widget_repo.save(widget)
    return widget, _STATUS_CREATED


def _build_placements(
    widget_repo: CmsWidgetRepository,
    widget_assignments: List[Tuple[str, str]],
    terms_archive_widget: CmsWidget,
) -> List[Dict[str, Any]]:
    """Resolve each (area, widget_slug) placement to a repository assignment dict.

    The ``terms-archive`` widget is the one this applier owns; every OTHER
    referenced widget (header/breadcrumbs/footer) is a pre-existing core widget
    looked up by slug — a placement whose widget is absent is skipped, exactly as
    the seeder's ``_get_or_create_layout`` tolerates a missing widget.
    """
    placements: List[Dict[str, Any]] = []
    for sort_order, (area_name, widget_slug) in enumerate(widget_assignments):
        if widget_slug == populate_cms.TERMS_ARCHIVE_WIDGET_SLUG:
            widget: Optional[CmsWidget] = terms_archive_widget
        else:
            widget = widget_repo.find_by_slug(widget_slug)
        if widget is None:
            print(f"    ! widget '{widget_slug}' absent — placement skipped")
            continue
        placements.append(
            {
                "area_name": area_name,
                "widget_id": str(widget.id),
                "sort_order": sort_order,
            }
        )
    return placements


def _ensure_terms_archive_layout(
    layout_repo: CmsLayoutRepository,
    layout_widget_repo: CmsLayoutWidgetRepository,
    widget_repo: CmsWidgetRepository,
    terms_archive_widget: CmsWidget,
) -> str:
    """Create the ``terms-archive`` layout CREATE-ONLY. Returns the status.

    An existing layout is left completely untouched (non-destructive). When
    absent it is created from the canonical bundled row (its four areas), and the
    seeder-owned placements whose widget exists are assigned.
    """
    existing = layout_repo.find_by_slug(populate_cms.TERMS_ARCHIVE_LAYOUT_SLUG)
    if existing is not None:
        return _STATUS_ALREADY_PRESENT

    row = populate_cms.terms_archive_layout_row()
    if row is None:
        raise TermsArchiveApplyError(
            "canonical 'terms-archive' layout row is missing from the bundled "
            "layout JSON; cannot create the layout"
        )

    layout = CmsLayout(
        slug=populate_cms.TERMS_ARCHIVE_LAYOUT_SLUG,
        name=row["name"],
        description=row.get("description"),
        areas=row["areas"],
        sort_order=row.get("sort_order", 0),
        is_active=bool(row.get("is_active", True)),
    )
    layout_repo.save(layout)

    placements = _build_placements(
        widget_repo, row.get("widget_assignments", []), terms_archive_widget
    )
    layout_widget_repo.replace_for_layout(str(layout.id), placements)
    return _STATUS_CREATED


def apply_terms_archive_layout(session) -> Dict[str, str]:
    """Ensure the terms-archive layout + widget exist (create-only, idempotent).

    Returns ``{"widget": <status>, "layout": <status>}`` where each status is
    ``created`` or ``already-present``. Non-destructive: existing rows are never
    overwritten.
    """
    widget_repo = CmsWidgetRepository(session)
    layout_repo = CmsLayoutRepository(session)
    layout_widget_repo = CmsLayoutWidgetRepository(session)

    widget, widget_status = _ensure_terms_archive_widget(widget_repo)
    layout_status = _ensure_terms_archive_layout(
        layout_repo, layout_widget_repo, widget_repo, widget
    )

    summary = {"widget": widget_status, "layout": layout_status}
    print(f"  Terms-archive layout applier: {summary}")
    return summary


def main() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from vbwd.extensions import db

    try:
        apply_terms_archive_layout(db.session)
    except SQLAlchemyError as exc:
        # Deploy invokes this unconditionally; a fresh instance may not have the
        # cms tables yet. Log and exit cleanly rather than fail the deploy.
        db.session.rollback()
        print(
            f"  terms-archive layout unavailable — skipped ({exc.__class__.__name__})"
        )


if __name__ == "__main__":
    from vbwd.app import create_app

    with create_app().app_context():
        main()
