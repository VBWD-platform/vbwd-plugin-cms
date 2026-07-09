#!/usr/bin/env python3
"""Install the ``super-header`` CMS widget onto an existing (production) database.

Deploy runs the destructive ``populate_cms.py`` seeders on NO instance (they
would overwrite operator content), so the newly-seeded ``super-header`` widget
never reaches an already-provisioned database that way. This applier is the safe
counterpart, in the exact mould of ``apply_pricing_card_defaults.py`` and
``apply_style_alignment.py``.

Two phases, in order:

* Phase 1 — CREATE-ONLY. If the ``super-header`` widget is ABSENT it is created
  from the canonical seed entry (``populate_cms._STANDALONE_VUE_WIDGETS``, so the
  applier and the seed can never drift) via ``CmsWidgetService.create_widget``.
  If it is already PRESENT its ``config`` is left completely untouched — an
  operator may have customised the logo / labels.
* Phase 2 — repoint every layout's ``header`` area to the super-header widget,
  preserving every other assignment (area_name, widget_id, sort_order) exactly.
  Idempotent: a header already pointing at super-header is left alone. This
  phase IS destructive to existing header assignments (explicitly authorised),
  so a rollback snapshot line is printed to stdout BEFORE any mutation — even in
  dry-run — mapping each affected layout slug to its full pre-change assignment
  list plus the layout id:

      SUPER_HEADER_ROLLBACK_JSON={"<slug>": {"layout_id": ..., "assignments": [
        {"area_name": ..., "widget_id": ..., "sort_order": ...}, ...]}, ...}

  This is the only rollback record on prod; keep it.

CLI:
* (no args) — DRY-RUN. Report what it WOULD do, emit the rollback JSON, write
  nothing, exit 0. A bare invocation NEVER mutates.
* ``--apply`` — actually perform both phases and commit.

Usage (matches how the sibling appliers document theirs):
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_super_header.py --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from plugins.cms.src.bin import populate_cms  # noqa: E402
from plugins.cms.src.repositories.cms_image_repository import (  # noqa: E402
    CmsImageRepository,
)
from plugins.cms.src.repositories.cms_layout_repository import (  # noqa: E402
    CmsLayoutRepository,
)
from plugins.cms.src.repositories.cms_layout_widget_repository import (  # noqa: E402
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_menu_item_repository import (  # noqa: E402
    CmsMenuItemRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import (  # noqa: E402
    CmsWidgetRepository,
)
from plugins.cms.src.services.cms_widget_service import (  # noqa: E402
    CmsWidgetService,
    CmsWidgetSlugConflictError,
)

SUPER_HEADER_SLUG = "super-header"
HEADER_AREA_NAME = "header"
ROLLBACK_LINE_PREFIX = "SUPER_HEADER_ROLLBACK_JSON="

# Layout paging: read the full set in bounded pages before any mutation, so we
# never mutate the collection we are iterating.
_LAYOUT_PAGE_SIZE = 100

# Per-layout phase-2 verdicts.
_STATUS_REPOINT = "repoint"
_STATUS_ALREADY_CURRENT = "already-current"
_STATUS_NO_HEADER = "no-header"

# The seed-entry keys the created widget copies verbatim.
_SEED_WIDGET_KEYS: Tuple[str, ...] = (
    "slug",
    "name",
    "widget_type",
    "content_json",
    "config",
)


class SuperHeaderApplyError(Exception):
    """Raised when the super-header widget cannot be created or found."""


def _load_super_header_seed() -> Optional[Dict[str, Any]]:
    """Return the canonical ``super-header`` seed entry, or None if it is gone.

    Sourced from ``populate_cms._STANDALONE_VUE_WIDGETS`` so the applier can
    never drift from what the seeder writes.
    """
    for entry in populate_cms._STANDALONE_VUE_WIDGETS:
        if entry.get("slug") == SUPER_HEADER_SLUG:
            return entry
    return None


def _ensure_super_header_widget(
    widget_service: CmsWidgetService,
    widget_repo: CmsWidgetRepository,
    apply_changes: bool,
):
    """Phase 1 — create the widget CREATE-ONLY. Returns (widget_or_None, status).

    status is one of ``already-present`` (left untouched), ``created`` (built
    from the seed entry), or ``would-create`` (dry-run, nothing written).
    """
    existing = widget_repo.find_by_slug(SUPER_HEADER_SLUG)
    if existing is not None:
        return existing, "already-present"

    seed = _load_super_header_seed()
    if seed is None:
        raise SuperHeaderApplyError(
            "canonical 'super-header' seed entry is missing from "
            "populate_cms._STANDALONE_VUE_WIDGETS; cannot create the widget"
        )

    if not apply_changes:
        return None, "would-create"

    create_data = {key: copy.deepcopy(seed[key]) for key in _SEED_WIDGET_KEYS}
    try:
        widget_service.create_widget(create_data)
    except (ValueError, CmsWidgetSlugConflictError) as exc:
        raise SuperHeaderApplyError(
            f"could not create the 'super-header' widget: {exc}"
        ) from exc

    created = widget_repo.find_by_slug(SUPER_HEADER_SLUG)
    if created is None:
        raise SuperHeaderApplyError(
            "'super-header' widget still not found after create_widget"
        )
    return created, "created"


def _snapshot_assignments(assignments) -> List[Dict[str, Any]]:
    """Full pre-change snapshot of a layout's assignments (all fields).

    ``required_access_level_ids`` is captured so the phase-2 repoint preserves it
    on every assignment; the rollback JSON exposes only the three spec'd fields.
    """
    return [
        {
            "area_name": assignment.area_name,
            "widget_id": str(assignment.widget_id),
            "sort_order": assignment.sort_order,
            "required_access_level_ids": list(
                assignment.required_access_level_ids or []
            ),
        }
        for assignment in assignments
    ]


def _iter_all_layouts(layout_repo: CmsLayoutRepository):
    """Yield every layout, one bounded page at a time (read-only)."""
    page = 1
    while True:
        result = layout_repo.find_all(page=page, per_page=_LAYOUT_PAGE_SIZE)
        items = result["items"]
        if not items:
            break
        for layout in items:
            yield layout
        if page >= result["pages"]:
            break
        page += 1


def _classify_layout(
    snapshot: List[Dict[str, Any]], super_header_id: Optional[str]
) -> str:
    """Decide the phase-2 verdict for one layout from its assignment snapshot."""
    header_assignments = [a for a in snapshot if a["area_name"] == HEADER_AREA_NAME]
    if not header_assignments:
        return _STATUS_NO_HEADER
    if super_header_id is not None and all(
        a["widget_id"] == super_header_id for a in header_assignments
    ):
        return _STATUS_ALREADY_CURRENT
    return _STATUS_REPOINT


def _build_header_plan(
    layout_repo: CmsLayoutRepository,
    layout_widget_repo: CmsLayoutWidgetRepository,
    super_header_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Read-only phase-2 plan: one entry per layout with its snapshot + verdict."""
    plan: List[Dict[str, Any]] = []
    for layout in _iter_all_layouts(layout_repo):
        snapshot = _snapshot_assignments(
            layout_widget_repo.find_by_layout(str(layout.id))
        )
        plan.append(
            {
                "layout_id": str(layout.id),
                "slug": layout.slug,
                "assignments": snapshot,
                "status": _classify_layout(snapshot, super_header_id),
            }
        )
    return plan


def _rollback_payload(plan: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rollback record for the affected (to-be-repointed) layouts only.

    Exposes exactly the three spec'd assignment fields; feeding this back through
    ``CmsLayoutWidgetRepository.replace_for_layout`` restores the original header
    widget_id.
    """
    return {
        entry["slug"]: {
            "layout_id": entry["layout_id"],
            "assignments": [
                {
                    "area_name": assignment["area_name"],
                    "widget_id": assignment["widget_id"],
                    "sort_order": assignment["sort_order"],
                }
                for assignment in entry["assignments"]
            ],
        }
        for entry in plan
        if entry["status"] == _STATUS_REPOINT
    }


def _emit_rollback(payload: Dict[str, Any]) -> None:
    """Print the single rollback line to stdout (before any mutation)."""
    compact = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    print(f"{ROLLBACK_LINE_PREFIX}{compact}")


def _repoint_layout_header(
    layout_widget_repo: CmsLayoutWidgetRepository,
    entry: Dict[str, Any],
    super_header_id: str,
) -> None:
    """Rewrite a layout's header assignment(s) to super-header, keeping the rest."""
    new_assignments = [
        {
            "area_name": assignment["area_name"],
            "widget_id": (
                super_header_id
                if assignment["area_name"] == HEADER_AREA_NAME
                else assignment["widget_id"]
            ),
            "sort_order": assignment["sort_order"],
            "required_access_level_ids": assignment["required_access_level_ids"],
        }
        for assignment in entry["assignments"]
    ]
    layout_widget_repo.replace_for_layout(entry["layout_id"], new_assignments)


def apply_super_header(session, apply_changes: bool) -> Dict[str, Any]:
    """Run both phases against ``session``; commit when ``apply_changes`` is True.

    Emits the rollback JSON line before any mutation (always). Returns a summary
    dict: ``widget`` (created | already-present | would-create), ``repointed``,
    ``already_current``, ``no_header``, ``applied``.
    """
    widget_repo = CmsWidgetRepository(session)
    widget_service = CmsWidgetService(
        widget_repo,
        CmsMenuItemRepository(session),
        CmsImageRepository(session),
    )
    layout_repo = CmsLayoutRepository(session)
    layout_widget_repo = CmsLayoutWidgetRepository(session)

    # Phase 1 — create-only.
    widget, widget_status = _ensure_super_header_widget(
        widget_service, widget_repo, apply_changes
    )
    super_header_id = str(widget.id) if widget is not None else None

    if apply_changes and super_header_id is None:
        raise SuperHeaderApplyError(
            "'super-header' widget is unavailable after phase 1; aborting"
        )

    # Phase 2 — plan (read-only), emit rollback, then mutate.
    plan = _build_header_plan(layout_repo, layout_widget_repo, super_header_id)
    to_repoint = [e for e in plan if e["status"] == _STATUS_REPOINT]
    already_current = [e for e in plan if e["status"] == _STATUS_ALREADY_CURRENT]
    no_header = [e for e in plan if e["status"] == _STATUS_NO_HEADER]

    _emit_rollback(_rollback_payload(plan))

    if apply_changes:
        assert super_header_id is not None  # guarded above
        for entry in to_repoint:
            _repoint_layout_header(layout_widget_repo, entry, super_header_id)
        session.commit()

    _print_summary(apply_changes, widget_status, to_repoint, already_current, no_header)
    return {
        "widget": widget_status,
        "repointed": len(to_repoint),
        "already_current": len(already_current),
        "no_header": len(no_header),
        "applied": apply_changes,
    }


def _print_summary(
    apply_changes: bool,
    widget_status: str,
    to_repoint: List[Dict[str, Any]],
    already_current: List[Dict[str, Any]],
    no_header: List[Dict[str, Any]],
) -> None:
    verb = "repointed" if apply_changes else "would repoint"
    mode = "APPLY" if apply_changes else "DRY-RUN"
    print(f"  Super-header applier ({mode}):")
    print(f"    widget: {widget_status}")
    print(f"    layouts {verb}: {len(to_repoint)}")
    print(f"    layouts already-current: {len(already_current)}")
    print(f"    layouts without a header area: {len(no_header)}")


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install the super-header CMS widget and repoint every layout's "
            "header area to it. Dry-run by default; pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform both phases and commit (default is a no-write dry-run).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    from vbwd.extensions import db

    try:
        apply_super_header(db.session, apply_changes=args.apply)
    except SuperHeaderApplyError as exc:
        db.session.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    from vbwd.app import create_app

    with create_app().app_context():
        sys.exit(main())
