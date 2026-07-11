#!/usr/bin/env python3
"""Import a CURATED set of three bundled CMS pages straight through the import service.

Container-side, no-HTTP, opt-in deploy step: it imports exactly THREE bundled
pages into whatever instance it runs against, directly through
``PostImportExportService.import_posts`` (direct DB session, no login). It exists
because the destructive ``populate_cms.py`` seeders run on NO instance (they
would overwrite operator content), so these three pages never reach an existing
database that way — this applier is the safe, idempotent counterpart.

Only these three files (relative to ``docs/imports/pages/``) are imported —
NEVER a glob of the whole directory, which would clobber unrelated pages (home
variants, page-widget-demo, …):

    pricing-native.json
    pricing-embedded.json
    docs-core-subscription-tarif-plans.json

``docs-core-subscription-tarif-plans.json`` is a deploy-bundled MIRROR of the
docs-portal source
``docs/marketing/cms-imports/vbwd-docs/vbwd-subscription-tarif-plans.json``
(re-enveloped into this plugin's native ``cms_posts`` shape). Regenerate it from
that source and keep the two in sync.

Import is upsert-by-``(type, slug)`` (the import service's contract), so a
re-run creates nothing new and reports ``updated`` counts — fully idempotent.
Each file is imported independently: a single failing file (e.g. an instance
missing the parent page / category) is logged and skipped, never fatal.

Usage (matches how deploy invokes it):
    docker compose exec -T -e PYTHONPATH=/app api \
        python /app/plugins/cms/src/bin/apply_cms_pages.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# The curated allowlist: exactly the three bundled pages this applier ships,
# relative to ``docs/imports/pages/``. Never expand this to a directory glob —
# importing every bundled page would overwrite unrelated pages (home variants,
# page-widget-demo). Keep it an explicit, reviewed tuple.
PAGE_FILES: Tuple[str, ...] = (
    "pricing-native.json",
    "pricing-embedded.json",
    "docs-core-subscription-tarif-plans.json",
)


def pages_dir() -> Path:
    """Absolute path to the plugin's bundled ``docs/imports/pages/`` directory."""
    return Path(__file__).resolve().parents[2] / "docs" / "imports" / "pages"


def normalize_envelope_items(payload: Any) -> List[Dict[str, Any]]:
    """Normalise any bundled-page envelope to a plain list of page items.

    Accepts the canonical ``{"items": [...]}`` envelope, this plugin's native
    ``{"vbwd_export": "cms_posts", ..., "cms_posts": [...]}`` envelope (which the
    import service does NOT understand — hence this normaliser), a bare list of
    items, or a single-item dict. Anything else (empty / metadata-only) yields an
    empty list, so a malformed file contributes nothing rather than raising.
    """
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload["items"]
        if isinstance(payload.get("cms_posts"), list):
            return payload["cms_posts"]
        if payload.get("slug") or payload.get("title") or payload.get("name"):
            return [payload]
    return []


def _load_items(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return normalize_envelope_items(payload)


def apply_cms_pages(session) -> Dict[str, Dict[str, int]]:
    """Import each curated page file through the import service; commit the session.

    Returns ``{filename: {"created": n, "updated": m}}``. Each file is imported
    independently: a per-file SQLAlchemyError (e.g. a missing parent/category on
    a fresh instance) is rolled back, logged, and skipped so the remaining files
    still import. Safe to run repeatedly — upsert-by-(type, slug).
    """
    from sqlalchemy.exc import SQLAlchemyError

    service = _build_import_service(session)
    directory = pages_dir()
    results: Dict[str, Dict[str, int]] = {}
    for filename in PAGE_FILES:
        path = directory / filename
        try:
            items = _load_items(path)
            if not items:
                print(f"  = page file '{filename}' has no items — skipped")
                continue
            summary = service.import_posts({"items": items})
            session.commit()
            results[filename] = summary
            print(
                f"  ~ page file '{filename}': "
                f"created={summary['created']} updated={summary['updated']}"
            )
        except SQLAlchemyError as exc:
            session.rollback()
            print(
                f"  ! page file '{filename}' failed — skipped "
                f"({exc.__class__.__name__})"
            )
    print(f"  Curated CMS pages: {results}")
    return results


def _build_import_service(session):
    """Compose ``PostImportExportService`` exactly as ``routes.py`` wires it.

    Same repository set over the given ``session`` so the applier reuses the one
    canonical import path (upsert, slug resolution) the admin route uses.
    """
    from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
    from plugins.cms.src.repositories.cms_post_content_block_repository import (
        CmsPostContentBlockRepository,
    )
    from plugins.cms.src.repositories.cms_post_widget_repository import (
        CmsPostWidgetRepository,
    )
    from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
    from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.post_term_repository import PostTermRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.services.post_import_export_service import (
        PostImportExportService,
    )

    return PostImportExportService(
        post_repo=PostRepository(session),
        layout_repo=CmsLayoutRepository(session),
        style_repo=CmsStyleRepository(session),
        term_repo=TermRepository(session),
        post_term_repo=PostTermRepository(session),
        content_block_repo=CmsPostContentBlockRepository(session),
        post_widget_repo=CmsPostWidgetRepository(session),
        widget_repo=CmsWidgetRepository(session),
    )


def main() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from vbwd.extensions import db

    try:
        apply_cms_pages(db.session)
    except SQLAlchemyError as exc:
        # Deploy invokes this unconditionally when the flag is set; a fresh
        # instance may not have the cms tables yet. Log and exit cleanly rather
        # than fail the deploy.
        db.session.rollback()
        print(f"  cms pages unavailable — skipped ({exc.__class__.__name__})")


if __name__ == "__main__":
    from vbwd.app import create_app

    with create_app().app_context():
        main()
