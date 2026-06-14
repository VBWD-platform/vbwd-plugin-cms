"""CMS demo seed + backfill hooks for ``flask reset-demo`` (S88).

``seed_catalog(session)`` seeds all CMS styles / widgets / layouts / pages /
unified content; ``run_backfill(session)`` folds the just-seeded legacy
``cms_page`` / ``cms_category`` rows into the unified ``cms_post`` / ``cms_term``
model. Both are registered into core's demo-data registry from the cms plugin's
``on_enable`` — ``seed_catalog`` as a catalog seeder (runs with the other
plugins) and ``run_backfill`` as a post-seed hook (runs LAST, after every
plugin's pages exist). Core imports no cms model (registry indirection).

DRY: the page/widget/layout authoring stays in ``src/bin/populate_cms.py``
(``populate_cms``) — this module is the thin session-aware seam over it and the
existing ``CmsBackfillService``.
"""
import logging

logger = logging.getLogger(__name__)


def seed_catalog(session) -> dict:
    """Seed CMS styles, widgets, layouts, pages and unified content.

    Delegates to the single ``populate_cms`` authoring function (which writes
    through ``db.session`` — the same session reset-demo passes here). Returns a
    small stats dict for the reset-demo summary.
    """
    from plugins.cms.src.bin.populate_cms import populate_cms
    from plugins.cms.src.models.cms_page import CmsPage
    from plugins.cms.src.models.cms_widget import CmsWidget
    from plugins.cms.src.models.cms_layout import CmsLayout

    populate_cms()

    return {
        "cms_pages": session.query(CmsPage).count(),
        "cms_widgets": session.query(CmsWidget).count(),
        "cms_layouts": session.query(CmsLayout).count(),
    }


def run_backfill(session) -> dict:
    """Fold legacy cms_page / cms_category rows into the unified model.

    Post-seed hook: runs after every plugin's catalog seeder so all seeded
    pages (shop, booking, ghrm, core CMS) are present before the backfill copies
    them into ``cms_post``. Idempotent — invokes ``CmsBackfillService`` directly
    (no shell subprocess).
    """
    from flask import current_app

    from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
    from plugins.cms.src.repositories.cms_category_repository import (
        CmsCategoryRepository,
    )
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )
    from plugins.cms.src.services.cms_backfill_service import CmsBackfillService

    event_dispatcher = getattr(current_app, "event_dispatcher", None)
    service = CmsBackfillService(
        page_repo=CmsPageRepository(session),
        category_repo=CmsCategoryRepository(session),
        post_repo=PostRepository(session),
        term_repo=TermRepository(session),
        event_dispatcher=event_dispatcher,
        routing_repo=CmsRoutingRuleRepository(session),
    )
    summary = service.backfill()
    session.commit()
    logger.info("[cms] reset-demo backfill: %s", summary)
    return {"cms_backfill_pages_copied": summary.get("pages_copied", 0)}
