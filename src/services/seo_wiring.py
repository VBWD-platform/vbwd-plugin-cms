"""Wiring for the SEO pipeline (S47.1) — invoked from ``CmsPlugin.on_enable``.

Two seams are connected here (and nowhere in core):
  1. the prerender writer subscribes to ``content.changed`` on the EventBus;
  2. the cms sitemap provider is registered with the core sitemap registry.

Both use a live ``db.session`` lazily (resolved per call), so the writer and
provider stay session-agnostic and unit-testable with doubles.
"""
import logging
import os
from typing import Any, Optional

from vbwd.events.bus import event_bus
from vbwd.services.filesystem.local import LocalFilesystemManager

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.services.indexnow_service import IndexNowSubmitter
from plugins.cms.src.services.seo_registry import (
    register_sitemap_provider,
    unregister_sitemap_provider,
)
from plugins.cms.src.services.post_service import CONTENT_CHANGED_EVENT
from plugins.cms.src.services.seo_asset_stamp import (
    SeoAssetStamper,
    iter_seo_html_relative_paths,
)
from plugins.cms.src.services.seo_full_page_renderer import (
    HttpFullPageRenderer,
)
from plugins.cms.src.services.dynamic_render_service import DynamicRenderService
from plugins.cms.src.services.render_cache import InMemoryTtlRenderCache
from plugins.cms.src.services.prerender_minifier import PrerenderMinifier
from plugins.cms.src.services.seo_post_loader import SeoPostLoader
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.services.seo_sitemap_provider import CmsSitemapProvider

logger = logging.getLogger(__name__)

_DEFAULT_VAR_DIR = "/app/var"

# Prerendered HTML lives under the ``seo`` namespace of the unified
# FilesystemManager (Sprint 58.2).
SEO_NAMESPACE = "seo"


def _var_dir() -> str:
    return os.environ.get("VBWD_VAR_DIR", _DEFAULT_VAR_DIR)


def _filesystem_manager() -> Any:
    """Resolve the core ``FilesystemManager`` for the SEO file IO.

    Rooted at the live ``VBWD_VAR_DIR`` (read per call, mirroring ``_session``)
    so the ``seo`` namespace resolves to the same ``<var>/seo`` directory used
    before the 58.2 migration. Reading the var dir live — rather than the
    container singleton, whose ``var_root`` is bound once at app boot —
    preserves the pre-existing contract that an updated ``VBWD_VAR_DIR`` takes
    effect without rebuilding the app. The manager is the core agnostic service
    (``vbwd.services.filesystem``); no new env var, no path change.
    """
    return LocalFilesystemManager(var_root=_var_dir())


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


_DEFAULT_HOME_SLUG = "index"


def _home_slug() -> str:
    """Resolve the cms ``home_slug`` from live config (lazy, S120).

    Read per call (mirroring ``_public_base_url``) so the prerender derives the
    ROOT canonical (``<base>/``) for the home post when its ``canonical_url``
    column is empty. Defaults to ``index`` when no app/config is available.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return _DEFAULT_HOME_SLUG
        cfg = config_store.get_config("cms") or {}
        return str(cfg.get("home_slug") or _DEFAULT_HOME_SLUG).strip() or (
            _DEFAULT_HOME_SLUG
        )
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] home_slug lookup failed: %s", exc)
        return _DEFAULT_HOME_SLUG


def _global_head_html() -> str:
    """Resolve the cms ``global_head_html`` raw setting from live config (lazy).

    Read per call (mirroring ``_public_base_url``) so an admin's saved head HTML
    (site-verification tags, analytics snippets) takes effect on the next
    prerender without re-enabling the plugin. The prerender writer splices this
    string into every page's ``<head>`` just before ``</head>`` so non-JS
    crawlers see it. Returns ``""`` when no app/config is available (nothing is
    spliced).
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return ""
        cfg = config_store.get_config("cms") or {}
        return cfg.get("global_head_html", "") or ""
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] global_head_html lookup failed: %s", exc)
        return ""


def _prerender_service_url() -> str:
    """Resolve the cms ``prerender_service_url`` from the live config (lazy).

    Read per call (mirroring ``_public_base_url``). When set, the prerender
    writer asks this external service for the COMPLETE page HTML (layout +
    content) and saves that; empty ⇒ the renderer is off and the writer keeps
    its content-only document (current behaviour). Returns ``""`` when no
    app/config is available.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return ""
        cfg = config_store.get_config("cms") or {}
        return cfg.get("prerender_service_url", "") or ""
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] prerender_service_url lookup failed: %s", exc)
        return ""


_SITEMAP_CONFIG_KEYS = (
    "sitemap_include_pages",
    "sitemap_excluded_slugs",
    "sitemap_include_terms",
    "sitemap_exclude_terms",
)


def _sitemap_config() -> dict:
    """Resolve the cms sitemap filter keys from live config (lazy, per call).

    Read per call (mirroring ``_public_base_url``) so an admin's saved sitemap
    filters take effect without re-enabling the plugin. Returns an empty dict
    when no app/config is available so the provider falls back to its
    "no filter" defaults (preserving the pre-S56 behaviour).
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return {}
        cfg = config_store.get_config("cms") or {}
        return {key: cfg[key] for key in _SITEMAP_CONFIG_KEYS if key in cfg}
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] sitemap config lookup failed: %s", exc)
        return {}


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


def _minify_prerender_output() -> bool:
    """Resolve the cms ``minify_prerender_output`` toggle from live config (lazy).

    Read per call (mirroring ``_seo_prerender_enabled``) so flipping the admin
    checkbox takes effect on the next prerender without re-enabling the plugin.
    When on, the writer minifies the inline ``<style>``/``<script>`` blocks and
    collapses inter-tag whitespace in the emitted file. Defaults to ``False``
    when no app/config is available so existing behaviour (pretty output) is
    preserved.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return False
        cfg = config_store.get_config("cms") or {}
        return bool(cfg.get("minify_prerender_output", False))
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] minify_prerender_output lookup failed: %s", exc)
        return False


_DEFAULT_RENDER_CACHE_TTL_SECONDS = 3600


def _seo_dynamic_render_enabled() -> bool:
    """Resolve the cms ``seo_dynamic_render_enabled`` toggle from live config.

    Master switch (read per call) for the on-demand full-page render served by
    the internal ``/_seo-render`` route. Defaults to ``False`` (off) so the
    route is disabled unless an operator opts in.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return False
        cfg = config_store.get_config("cms") or {}
        return bool(cfg.get("seo_dynamic_render_enabled", False))
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] seo_dynamic_render_enabled lookup failed: %s", exc)
        return False


def _seo_render_internal_token() -> str:
    """Resolve the cms ``seo_render_internal_token`` shared secret (live config).

    nginx (increment 2) injects it as ``X-VBWD-Render-Token`` when it routes a
    bot to the internal render route; an empty token disables the route (there
    is no valid secret to match). Read per call. Returns ``""`` when no
    app/config is available.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return ""
        cfg = config_store.get_config("cms") or {}
        return str(cfg.get("seo_render_internal_token", "") or "")
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] seo_render_internal_token lookup failed: %s", exc)
        return ""


def _seo_render_cache_ttl_seconds() -> int:
    """Resolve the cms ``seo_render_cache_ttl_seconds`` from live config (lazy).

    TTL applied to a cached on-demand render. Read per call so an admin's change
    takes effect on the next cache write. Falls back to the shipped default when
    unset or non-numeric.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return _DEFAULT_RENDER_CACHE_TTL_SECONDS
        cfg = config_store.get_config("cms") or {}
        return int(
            cfg.get("seo_render_cache_ttl_seconds", _DEFAULT_RENDER_CACHE_TTL_SECONDS)
        )
    except (TypeError, ValueError):
        return _DEFAULT_RENDER_CACHE_TTL_SECONDS
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.seo] seo_render_cache_ttl_seconds lookup failed: %s", exc)
        return _DEFAULT_RENDER_CACHE_TTL_SECONDS


# One process-wide render cache shared by every DynamicRenderService instance so
# a hit on one request is served to the next (the service itself is cheap and
# rebuilt per call; the cache is the stateful collaborator).
_render_cache = InMemoryTtlRenderCache()


def seo_render_internal_token() -> str:
    """Public accessor: the shared secret the internal render route validates."""
    return _seo_render_internal_token()


def seo_dynamic_render_available() -> bool:
    """True when on-demand render is enabled AND a renderer URL is configured.

    The internal render route serves 404 (disabled) unless both hold.
    """
    return _seo_dynamic_render_enabled() and bool(_prerender_service_url())


def build_dynamic_render_service() -> DynamicRenderService:
    """Assemble the on-demand render service (shared cache, lazy config)."""
    return DynamicRenderService(
        render_client=HttpFullPageRenderer(
            prerender_service_url=_prerender_service_url()
        ),
        cache=_render_cache,
        minifier=PrerenderMinifier(),
        minify_enabled=_minify_prerender_output,
        cache_ttl_seconds=_seo_render_cache_ttl_seconds,
    )


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
    filesystem_manager = _filesystem_manager()
    return SeoPrerenderWriter(
        var_dir=_var_dir(),
        post_loader=SeoPostLoader(_session()),
        canonical_rewrite_checker=_canonical_is_rewritten,
        asset_stamper=SeoAssetStamper(
            _fe_dist_dir(),
            filesystem_manager=filesystem_manager,
            public_base_url=_public_base_url(),
        ),
        style_css_resolver=_resolve_post_css,
        filesystem_manager=filesystem_manager,
        full_page_renderer=HttpFullPageRenderer(
            prerender_service_url=_prerender_service_url()
        ),
        global_head_html_resolver=_global_head_html,
        minifier=PrerenderMinifier() if _minify_prerender_output() else None,
        public_base_url=_public_base_url(),
        home_slug=_home_slug(),
    )


def restamp_prerendered_assets() -> int:
    """Deploy hook: re-stamp the entry tags in every ``${VAR_DIR}/seo/*.html``.

    Called after a frontend deploy (which changes the build's content hashes) so
    real users' SPA still boots from the prerendered files. Bots are unaffected
    either way. Returns the number of files rewritten.
    """
    seo_dir = os.path.join(_var_dir(), "seo")
    rewritten = SeoAssetStamper(
        _fe_dist_dir(),
        filesystem_manager=_filesystem_manager(),
        public_base_url=_public_base_url(),
    ).restamp_all(seo_dir)
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
    filesystem_manager = _filesystem_manager()
    removed = 0
    for relative_path in iter_seo_html_relative_paths(filesystem_manager):
        filesystem_manager.delete(SEO_NAMESPACE, relative_path)
        removed += 1
    logger.info("[cms.seo] Purged %d prerendered file(s).", removed)
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


# ── on-demand render-cache invalidation (S118 Track B, increment 4) ──────────
#
# The same process-wide cache the ``/_seo-render`` route serves from is purged on
# a domain change so a bot never receives a stale page. The invalidation
# subscribers are a no-op unless on-demand render is available (enabled AND a
# renderer URL is configured) — mirroring how the writer guards on its toggle.

# Payload keys another vertical MAY carry a canonical public path in. The cms
# plugin never COMPUTES another vertical's URL (core-agnostic); it only reads a
# path the emitter chose to publish, else purges coarsely.
_RENDER_PATH_PAYLOAD_KEYS = ("path", "url", "canonical")

# Other verticals' change events that should purge the render cache. Subscribed
# by NAME string only (no cross-plugin import), so the cms plugin stays agnostic.
# ``booking.*``/``dataset.*`` list the VERIFIED emitter names plus the sprint's
# documented ``<domain>.changed`` alias; ``product.changed``/``ghrm.changed`` are
# the documented contract names (no emitter today — see the increment report).
_VERTICAL_CHANGE_EVENTS = (
    "product.changed",
    "booking.changed",
    "booking.created",
    "booking.cancelled",
    "booking.cancelled_by_provider",
    "booking.rescheduled",
    "booking.completed",
    "dataset.changed",
    "dataset.new",
    "dataset.updated",
    "ghrm.changed",
)


def _public_path_for_slug(slug: Optional[str]) -> str:
    """Derive a post's public path the same way the prerender writer keys files.

    ``/`` for the home/empty slug, else ``/<slug>`` (leading/trailing slashes
    normalised). ``DynamicRenderService`` re-normalises the key, so equivalent
    forms collapse to one cache entry.
    """
    cleaned = (slug or "").strip().strip("/")
    return "/" + cleaned if cleaned else "/"


def _render_path_from_payload(data: Optional[dict]) -> Optional[str]:
    """First non-empty canonical path an event payload carries, else ``None``."""
    if not data:
        return None
    for key in _RENDER_PATH_PAYLOAD_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _on_content_changed_invalidate(_event_name: str, data: dict) -> None:
    """Purge the render cache for a changed CMS post's public path (precise)."""
    if not seo_dynamic_render_available():
        return
    try:
        path = _public_path_for_slug((data or {}).get("slug"))
        build_dynamic_render_service().invalidate(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[cms.seo] render-cache invalidate failed for %s: %s", data, exc)


def _on_vertical_changed_invalidate(event_name: str, data: dict) -> None:
    """Purge the render cache on another vertical's change (best-effort).

    The cms plugin cannot compute another vertical's URL, so it purges just the
    canonical path the payload carries; when none is present it falls back to a
    coarse ``invalidate_all`` (logged) so a stale price/availability page is
    never served. Missing keys ⇒ coarse purge, never a crash (Liskov-safe).
    """
    if not seo_dynamic_render_available():
        return
    try:
        service = build_dynamic_render_service()
        path = _render_path_from_payload(data)
        if path:
            service.invalidate(path)
        else:
            logger.info(
                "[cms.seo] '%s' carried no public path; purging all render-cache "
                "entries.",
                event_name,
            )
            service.invalidate_all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[cms.seo] render-cache invalidate failed for %s: %s", data, exc)


# ── IndexNow submission (instant crawl-freshness ping) ───────────────────────
#
# On a published-post change the plugin POSTs the canonical URL to IndexNow so
# Bing/Yandex/Seznam recrawl it immediately ("Discovered but not crawled" fix).
# Streaming/per-change (Bing guidance) and best-effort — a failed ping never
# breaks the publish flow. The verification key file is served at the site root
# by ``seo_routes.indexnow_key_file``.

_DEFAULT_INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


def _indexnow_enabled() -> bool:
    """Resolve the cms ``indexnow_enabled`` toggle from live config (lazy).

    Read per call (mirroring ``_seo_prerender_enabled``). Defaults to ``False``
    (off) so nothing is submitted unless an operator opts in.
    """
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return False
        cfg = config_store.get_config("cms") or {}
        return bool(cfg.get("indexnow_enabled", False))
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.indexnow] indexnow_enabled lookup failed: %s", exc)
        return False


def _indexnow_key() -> str:
    """Resolve the cms ``indexnow_key`` from live config (lazy). Empty ⇒ off."""
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return ""
        cfg = config_store.get_config("cms") or {}
        return str(cfg.get("indexnow_key", "") or "")
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.indexnow] indexnow_key lookup failed: %s", exc)
        return ""


def _indexnow_endpoint() -> str:
    """Resolve the cms ``indexnow_endpoint`` from live config, else the default."""
    try:
        from flask import current_app

        config_store = getattr(current_app, "config_store", None)
        if config_store is None:
            return _DEFAULT_INDEXNOW_ENDPOINT
        cfg = config_store.get_config("cms") or {}
        return str(cfg.get("indexnow_endpoint", "") or _DEFAULT_INDEXNOW_ENDPOINT)
    except Exception as exc:  # pragma: no cover - defensive (no app context)
        logger.warning("[cms.indexnow] indexnow_endpoint lookup failed: %s", exc)
        return _DEFAULT_INDEXNOW_ENDPOINT


def indexnow_available() -> bool:
    """True when IndexNow is enabled AND a key AND a ``public_base_url`` are set.

    The subscriber is a no-op unless all three hold (mirroring
    ``seo_dynamic_render_available``): without a base URL there is no absolute
    URL to submit, and without a key there is nothing to authorize with.
    """
    return _indexnow_enabled() and bool(_indexnow_key()) and bool(_public_base_url())


def build_indexnow_submitter() -> IndexNowSubmitter:
    """Assemble the IndexNow submitter from live config (lazy per call)."""
    return IndexNowSubmitter(
        public_base_url=_public_base_url(),
        key=_indexnow_key(),
        endpoint=_indexnow_endpoint(),
    )


def _on_content_changed_indexnow(_event_name: str, data: dict) -> None:
    """Ping IndexNow with a published CMS post's canonical URL (best-effort)."""
    if not indexnow_available():
        return
    if (data or {}).get("status") != POST_STATUS_PUBLISHED:
        return
    try:
        path = _public_path_for_slug((data or {}).get("slug"))
        build_indexnow_submitter().submit(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[cms.indexnow] submit for %s failed: %s", data, exc)


# Track the registered provider so a repeat enable (e.g. per-test app) replaces
# rather than accumulates it.
_active_provider: Optional[CmsSitemapProvider] = None


def register_seo_pipeline() -> CmsSitemapProvider:
    """Subscribe the prerender writer + register the sitemap provider."""
    global _active_provider
    event_bus.subscribe(CONTENT_CHANGED_EVENT, _on_content_changed)
    # Render-cache invalidation (increment 4): precise on CMS content, best-effort
    # on other verticals. The EventBus dedups identical (name, callback) pairs, so
    # re-enabling (per-test app) never double-subscribes these module-level fns.
    event_bus.subscribe(CONTENT_CHANGED_EVENT, _on_content_changed_invalidate)
    # IndexNow ping on a published-post change. Same EventBus dedup guarantee,
    # so re-enabling (per-test app) never double-subscribes this module-level fn.
    event_bus.subscribe(CONTENT_CHANGED_EVENT, _on_content_changed_indexnow)
    for vertical_event_name in _VERTICAL_CHANGE_EVENTS:
        event_bus.subscribe(vertical_event_name, _on_vertical_changed_invalidate)
    if _active_provider is not None:
        unregister_sitemap_provider(_active_provider)
    _active_provider = CmsSitemapProvider(
        SeoPostLoader(_session()),
        public_base_url_provider=_public_base_url,
        sitemap_config_provider=_sitemap_config,
    )
    register_sitemap_provider(_active_provider)
    return _active_provider


def unregister_seo_pipeline() -> None:
    """Unsubscribe the writer + unregister the provider (plugin disable)."""
    global _active_provider
    event_bus.unsubscribe(CONTENT_CHANGED_EVENT, _on_content_changed)
    event_bus.unsubscribe(CONTENT_CHANGED_EVENT, _on_content_changed_invalidate)
    event_bus.unsubscribe(CONTENT_CHANGED_EVENT, _on_content_changed_indexnow)
    for vertical_event_name in _VERTICAL_CHANGE_EVENTS:
        event_bus.unsubscribe(vertical_event_name, _on_vertical_changed_invalidate)
    if _active_provider is not None:
        unregister_sitemap_provider(_active_provider)
        _active_provider = None
