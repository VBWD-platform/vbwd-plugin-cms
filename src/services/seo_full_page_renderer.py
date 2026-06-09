"""Full-page renderer port for the SEO prerender writer.

The content-only document the writer builds carries the post body but NOT the
public layout (header-nav / breadcrumb / footer / container) — that is drawn by
the SPA after hydration. Anonymous visitors are served the static file by
nginx, so they would see no layout. This port lets an EXTERNAL renderer produce
the COMPLETE page HTML (layout + content) captured from the live SPA; the
writer saves that when available and falls back to the content-only document
otherwise (so behaviour is unchanged when unconfigured).

``render_full_page`` is best-effort by contract: it returns ``None`` (never
raises) when the renderer is disabled, unreachable, or returns a non-HTML /
non-200 response, so the caller can fall back deterministically.
"""
import logging
from typing import Optional, Protocol

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 20
_PRERENDER_PATH = "/prerender"
_HTML_MARKER = "<html"


class IFullPageRenderer(Protocol):
    """Produces the complete ``<!doctype html>…</html>`` for a page, or None."""

    def render_full_page(self, slug: str, language: Optional[str]) -> Optional[str]:
        ...


class HttpFullPageRenderer(IFullPageRenderer):
    """Asks an external prerender service for the complete page HTML over HTTP.

    POSTs ``{"slug", "language"}`` to ``<prerender_service_url>/prerender`` and
    returns the response body when it is a 200 carrying an HTML document. An
    empty ``prerender_service_url`` disables the renderer (returns ``None`` with
    no HTTP call), which is the configured-off default.
    """

    def __init__(
        self,
        prerender_service_url: str,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._prerender_service_url = prerender_service_url or ""
        self._timeout_seconds = timeout_seconds

    def render_full_page(self, slug: str, language: Optional[str]) -> Optional[str]:
        if not self._prerender_service_url:
            return None

        endpoint = self._prerender_service_url.rstrip("/") + _PRERENDER_PATH
        try:
            response = requests.post(
                endpoint,
                json={"slug": slug, "language": language},
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # best-effort: any failure ⇒ fall back
            logger.warning("[cms.seo] full-page render failed for '%s': %s", slug, exc)
            return None

        body = response.text or ""
        if response.status_code == 200 and _HTML_MARKER in body.lower():
            return body

        logger.warning(
            "[cms.seo] full-page render for '%s' returned no usable HTML "
            "(status=%s, body_len=%d)",
            slug,
            response.status_code,
            len(body),
        )
        return None
