#!/usr/bin/env python3
"""Apply the edge-alignment patch to every CmsStyle.

Loads every style via the repository, runs ``apply_edge_align`` on its
source_css and persists the result through ``CmsStyleService.update_style``
(the same update path the admin UI uses — no raw SQL). Idempotent: re-running
leaves already-aligned styles untouched and reports them as "already-current".

Usage (matches how deploy / seed invokes it):
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_style_alignment.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from plugins.cms.src.repositories.cms_style_repository import (  # noqa: E402
    CmsStyleRepository,
)
from plugins.cms.src.services.cms_style_service import CmsStyleService  # noqa: E402
from plugins.cms.src.services.style_edge_align import apply_edge_align  # noqa: E402


def apply_alignment_to_all_styles(session) -> Dict[str, int]:
    """Align every style's source_css. Returns {'updated', 'already_current'}.

    Persists each changed style through ``CmsStyleService.update_style`` so the
    single canonical update path (validation, save) is reused.
    """
    repository = CmsStyleRepository(session)
    service = CmsStyleService(repository)

    page = 1
    per_page = 100
    updated = 0
    already_current = 0
    while True:
        result = repository.find_all(page=page, per_page=per_page)
        styles = result["items"]
        if not styles:
            break
        for style in styles:
            current_css = style.source_css or ""
            aligned_css = apply_edge_align(current_css)
            if aligned_css == current_css:
                already_current += 1
                print(f"  = style '{style.slug}' (already-current)")
                continue
            service.update_style(str(style.id), {"source_css": aligned_css})
            updated += 1
            print(f"  ~ style '{style.slug}' (aligned)")
        if page >= result["pages"]:
            break
        page += 1

    print(f"  Edge-alignment: {updated} updated, " f"{already_current} already-current")
    return {"updated": updated, "already_current": already_current}


def main() -> None:
    from vbwd.extensions import db

    apply_alignment_to_all_styles(db.session)


if __name__ == "__main__":
    from vbwd.app import create_app

    with create_app().app_context():
        main()
