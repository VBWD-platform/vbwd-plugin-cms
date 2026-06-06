"""Wiring for the SEO pipeline (S47.1) — invoked from ``CmsPlugin.on_enable``.

Two seams are connected here (and nowhere in core):
  1. the prerender writer subscribes to ``content.changed`` on the EventBus;
  2. the cms sitemap provider is registered with the core sitemap registry.

Both use a live ``db.session`` lazily (resolved per call), so the writer and
provider stay session-agnostic and unit-testable with doubles.
"""
import logging
import os
from typing import Optional

from vbwd.events.bus import event_bus
from vbwd.services.seo_registry import (
    register_sitemap_provider,
    unregister_sitemap_provider,
)

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.services.post_service import CONTENT_CHANGED_EVENT
from plugins.cms.src.services.seo_asset_stamp import SeoAssetStamper
from plugins.cms.src.services.seo_post_loader import SeoPostLoader
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.services.seo_sitemap_provider import CmsSitemapProvider

logger = logging.getLogger(__name__)

_DEFAULT_VAR_DIR = "/app/var"


def _var_dir() -> str:
    return os.environ.get("VBWD_VAR_DIR", _DEFAULT_VAR_DIR)


def _session():
    from vbwd.extensions import db

    return db.session


def _public_base_url() -> str:
    """Resolve the cms ``public_base_url`` from the live config (lazy).

    Read per call (mirroring ``_session``) from the app's config store so the
    sitemap provider builds an absolute ``loc`` (``<base>/<slug>``) for any
    published post that has no stored ``canonical_url`` — the same fallback the
    RSS feed uses (DRY). Returns ``""`` when no app/config is available.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return ""
        cfg = config_store.get_config("cms") or {}
        return cfg.get("public_base_url", "") or ""
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] public_base_url lookup failed: %s", exc)
        return ""


def _seo_prerender_enabled() -> bool:
    """Resolve the cms ``seo_prerender_enabled`` toggle from live config (lazy).

    Read per call (mirroring ``_public_base_url``) so flipping the admin
    checkbox takes effect without re-enabling the plugin. When off, the app
    serves the SPA only and no prerendered SEO HTML is written on content
    changes. Defaults to ``True`` when no app/config is available so existing
    behaviour (prerender on) is preserved.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return True
        cfg = config_store.get_config("cms") or {}
        return bool(cfg.get("seo_prerender_enabled", True))
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] seo_prerender_enabled lookup failed: %s", exc)
        return True


def _canonical_is_rewritten(slug: str) -> bool:
    """True if an active rewrite rule targets this canonical slug (cloaking).

    A context-dependent rewrite silently serving different content on a
    canonical indexed URL is disallowed; the writer skips + logs it.
    """
    try:
        normalized = (slug or "").strip("/")
        count = (
            _session()
            .query(CmsRoutingRule)
            .filter(
                CmsRoutingRule.is_rewrite.is_(True),
                CmsRoutingRule.is_active.is_(True),
                CmsRoutingRule.target_slug == normalized,
            )
            .count()
        )
        return count > 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[cms.seo] rewrite check failed for '%s': %s", slug, exc)
        return False


def _fe_dist_dir() -> Optional[str]:
    return os.environ.get("VBWD_FE_DIST_DIR")


def _resolve_post_css(post) -> str:
    """The CSS a post renders with: its explicit style, else the active default
    style, plus the page's own ``source_css`` (CSS tab) layered on top — the
    same resolution the public renderer applies, inlined for the static page."""
    from plugins.cms.src.repositories.cms_style_repository import (
        CmsStyleRepository,
    )

    repo = CmsStyleRepository(_session())
    style = None
    if getattr(post, "style_id", None):
        style = repo.find_by_id(str(post.style_id))
    if style is None:
        default = repo.find_default()
        if default is not None and getattr(default, "is_active", True):
            style = default
    parts = []
    if style is not None and getattr(style, "source_css", None):
        parts.append(style.source_css)
    if getattr(post, "source_css", None):
        parts.append(post.source_css)
    return "\n".join(parts)


def _build_writer() -> SeoPrerenderWriter:
    return SeoPrerenderWriter(
        var_dir=_var_dir(),
        post_loader=SeoPostLoader(_session()),
        canonical_rewrite_checker=_canonical_is_rewritten,
        asset_stamper=SeoAssetStamper(_fe_dist_dir()),
        style_css_resolver=_resolve_post_css,
    )


def restamp_prerendered_assets() -> int:
    """Deploy hook: re-stamp the entry tags in every ``${VAR_DIR}/seo/*.html``.

    Called after a frontend deploy (which changes the build's content hashes) so
    real users' SPA still boots from the prerendered files. Bots are unaffected
    either way. Returns the number of files rewritten.
    """
    seo_dir = os.path.join(_var_dir(), "seo")
    rewritten = SeoAssetStamper(_fe_dist_dir()).restamp_all(seo_dir)
    logger.info(
        "[cms.seo] Re-stamped %d prerendered file(s) in '%s'.", rewritten, seo_dir
    )
    return rewritten


def purge_prerendered() -> int:
    """Manual cleanup: delete every prerendered ``${VAR_DIR}/seo/*.html``.

    nginx serves prerendered pages purely by file existence, so switching the
    ``seo_prerender_enabled`` toggle off only stops *future* writes — the files
    already on disk keep being served. This removes them (recursively, since
    nested slugs write ``seo/<a>/<b>.html``) so traffic falls through to the
    SPA. Non-``.html`` files are left untouched. Returns the number removed.
    """
    seo_dir = os.path.join(_var_dir(), "seo")
    if not os.path.isdir(seo_dir):
        return 0
    removed = 0
    for root, _dirs, files in os.walk(seo_dir):
        for name in files:
            if name.endswith(".html"):
                os.remove(os.path.join(root, name))
                removed += 1
    logger.info("[cms.seo] Purged %d prerendered file(s) from '%s'.", removed, seo_dir)
    return removed


def regenerate_prerendered() -> int:
    """Manual rebuild: (re)write a prerendered file for every published post.

    Writes directly via the writer (not the automatic ``content.changed`` path),
    so it runs regardless of the ``seo_prerender_enabled`` toggle — a deliberate
    admin override. Use it to (re)build files for content that predates the
    writer or arrived via bulk import/backfill. Returns the number written.
    """
    writer = _build_writer()
    loader = SeoPostLoader(_session())
    written = 0
    for post in loader.iter_candidate_posts():
        writer.handle_content_changed({"post_id": str(post.id)})
        written += 1
    logger.info("[cms.seo] Regenerated %d prerendered file(s).", written)
    return written


def _on_content_changed(_event_name: str, data: dict) -> None:
    """EventBus subscriber: keep the prerender file in sync with the post."""
    if not _seo_prerender_enabled():
        return
    try:
        _build_writer().handle_content_changed(data)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[cms.seo] prerender failed for %s: %s", data, exc)


# Track the registered provider so a repeat enable (e.g. per-test app) replaces
# rather than accumulates it.
_active_provider: Optional[CmsSitemapProvider] = None


def register_seo_pipeline() -> CmsSitemapProvider:
    """Subscribe the prerender writer + register the sitemap provider."""
    global _active_provider
    event_bus.subscribe(CONTENT_CHANGED_EVENT, _on_content_changed)
    if _active_provider is not None:
        unregister_sitemap_provider(_active_provider)
    _active_provider = CmsSitemapProvider(
        SeoPostLoader(_session()),
        public_base_url_provider=_public_base_url,
    )
    register_sitemap_provider(_active_provider)
    return _active_provider


def unregister_seo_pipeline() -> None:
    """Unsubscribe the writer + unregister the provider (plugin disable)."""
    global _active_provider
    event_bus.unsubscribe(CONTENT_CHANGED_EVENT, _on_content_changed)
    if _active_provider is not None:
        unregister_sitemap_provider(_active_provider)
        _active_provider = None
