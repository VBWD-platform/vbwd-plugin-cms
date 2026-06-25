"""CMS demo seed hook for ``flask reset-demo`` (S88).

``seed_catalog(session)`` seeds all CMS styles / widgets / layouts and the
unified ``cms_post`` / ``cms_term`` content directly (the legacy ``cms_page`` /
``cms_category`` round-trip + the post-seed backfill hook were retired in S105).
Registered into core's demo-data registry from the cms plugin's ``on_enable`` as
a catalog seeder. Core imports no cms model (registry indirection).

DRY: the page/widget/layout authoring stays in ``src/bin/populate_cms.py``
(``populate_cms``) — this module is the thin session-aware seam over it.
"""
import logging

logger = logging.getLogger(__name__)


def seed_catalog(session) -> dict:
    """Seed CMS styles, widgets, layouts and the unified content.

    Delegates to the single ``populate_cms`` authoring function (which writes
    through ``db.session`` — the same session reset-demo passes here). Returns a
    small stats dict for the reset-demo summary.
    """
    from plugins.cms.src.bin.populate_cms import populate_cms
    from plugins.cms.src.models.cms_post import CmsPost
    from plugins.cms.src.models.cms_widget import CmsWidget
    from plugins.cms.src.models.cms_layout import CmsLayout

    populate_cms()

    return {
        "cms_posts": session.query(CmsPost).count(),
        "cms_widgets": session.query(CmsWidget).count(),
        "cms_layouts": session.query(CmsLayout).count(),
    }
