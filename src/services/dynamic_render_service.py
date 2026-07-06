"""S118 Track B — the on-demand full-page render brain (render-on-miss + cache).

The nginx bot branch (increment 2) routes a crawler request for a public route
to ``GET /api/v1/cms/_seo-render?path=…``; this service is what that route
calls. On a cache miss it asks the render client for the full static HTML of the
fe-user SPA at ``path``, minifies it (when the flag is on), caches it under a
normalised path key with a TTL, and returns it. On a render miss it returns
``None`` and caches NOTHING (no negative-cache poisoning) so the route can 502
and nginx falls back to the SPA shell — the site never 5xx's on a render miss.

Event-driven invalidation (increment 4) purges cache keys through
``invalidate``/``invalidate_all``.

Config is resolved lazily (mirroring the ``seo_wiring`` resolvers) so an admin
flipping ``minify_prerender_output`` / ``seo_render_cache_ttl_seconds`` takes
effect on the next render without re-enabling the plugin.
"""
import logging
from typing import Callable, Optional

from plugins.cms.src.services.prerender_minifier import PrerenderMinifier
from plugins.cms.src.services.render_cache import RenderCache
from plugins.cms.src.services.seo_full_page_renderer import IFullPageRenderer

logger = logging.getLogger(__name__)


class DynamicRenderService:
    """Serve a route's full HTML from cache, rendering on demand on a miss."""

    def __init__(
        self,
        render_client: IFullPageRenderer,
        cache: RenderCache,
        minifier: Optional[PrerenderMinifier],
        minify_enabled: Callable[[], bool],
        cache_ttl_seconds: Callable[[], int],
    ) -> None:
        self._render_client = render_client
        self._cache = cache
        # The minifier TOOL (may be None to disable minification entirely); the
        # per-render decision is the lazy ``minify_enabled`` resolver.
        self._minifier = minifier
        self._minify_enabled = minify_enabled
        self._cache_ttl_seconds = cache_ttl_seconds

    def render(self, path: str) -> Optional[str]:
        """Return the full HTML for ``path`` (cache hit or on-demand render).

        Returns ``None`` when the renderer yields no usable HTML — the caller
        should 502 so nginx falls back to the SPA shell. Misses are NOT cached.
        """
        key = self._normalise(path)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        html = self._render_client.render_path(path)
        if html is None:
            return None

        if self._minifier is not None and self._minify_enabled():
            html = self._minifier.minify(html)

        self._cache.set(key, html, self._cache_ttl_seconds())
        return html

    def invalidate(self, path: str) -> None:
        """Purge the cached render for a single path (event-driven refresh)."""
        self._cache.delete(self._normalise(path))

    def invalidate_all(self) -> None:
        """Purge every cached render (e.g. a global content/layout change)."""
        self._cache.clear()

    @staticmethod
    def _normalise(path: str) -> str:
        """Canonicalise a path into a cache key.

        Ensures a single leading slash and drops a trailing slash (except the
        root) so ``/pricing`` and ``/pricing/`` share one entry — no cache
        fragmentation across equivalent URLs.
        """
        cleaned = (path or "").strip()
        if not cleaned.startswith("/"):
            cleaned = "/" + cleaned
        if len(cleaned) > 1:
            cleaned = cleaned.rstrip("/")
        return cleaned or "/"
