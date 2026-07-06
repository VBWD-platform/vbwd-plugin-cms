"""Full-page renderer port for the SEO prerender writer + dynamic render brain.

The content-only document the writer builds carries the post body but NOT the
public layout (header-nav / breadcrumb / footer / container) — that is drawn by
the SPA after hydration. Anonymous visitors are served the static file by
nginx, so they would see no layout. This port lets an EXTERNAL renderer produce
the COMPLETE page HTML (layout + content) captured from the live SPA; the
writer saves that when available and falls back to the content-only document
otherwise (so behaviour is unchanged when unconfigured).

The renderer service exposes ``GET <base>/render?path=<url-encoded path>`` and
returns the FULL static HTML of the fe-user SPA at that path (200 + ``<html…>``)
or a non-200 on failure. It handles its own loop-guard (it fetches fe-user with
a browser UA + ``X-VBWD-Render: 1`` so nginx serves the SPA shell, not the
render-cache). The backend just calls it and treats non-200 / non-HTML as a
miss.

``render_path`` / ``render_full_page`` are best-effort by contract: they return
``None`` (never raise) when the renderer is disabled, unreachable, or returns a
non-HTML / non-200 response, so the caller can fall back deterministically.
"""
import logging
from typing import Optional, Protocol

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 20
_RENDER_PATH = "/render"
_HTML_MARKER = "<html"


class IFullPageRenderer(Protocol):
    """Produces the complete ``<!doctype html>…</html>`` for a page, or None."""

    def render_path(self, path: str) -> Optional[str]:
        ...

    def render_full_page(self, slug: str, language: Optional[str]) -> Optional[str]:
        ...


class HttpFullPageRenderer(IFullPageRenderer):
    """Asks an external render service for the complete page HTML over HTTP.

    ``GET <prerender_service_url>/render?path=<path>`` returns the response body
    when it is a 200 carrying an HTML document. An empty ``prerender_service_url``
    disables the renderer (returns ``None`` with no HTTP call), which is the
    configured-off default.
    """

    def __init__(
        self,
        prerender_service_url: str,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._prerender_service_url = prerender_service_url or ""
        self._timeout_seconds = timeout_seconds

    def render_path(self, path: str) -> Optional[str]:
        """Render the SPA at ``path`` to full static HTML, or ``None`` on a miss."""
        if not self._prerender_service_url:
            return None

        endpoint = self._prerender_service_url.rstrip("/") + _RENDER_PATH
        try:
            response = requests.get(
                endpoint,
                params={"path": path},
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # best-effort: any failure ⇒ fall back
            logger.warning("[cms.seo] full-page render failed for '%s': %s", path, exc)
            return None

        body = response.text or ""
        if response.status_code == 200 and _HTML_MARKER in body.lower():
            return body

        logger.warning(
            "[cms.seo] full-page render for '%s' returned no usable HTML "
            "(status=%s, body_len=%d)",
            path,
            response.status_code,
            len(body),
        )
        return None

    def render_full_page(self, slug: str, language: Optional[str]) -> Optional[str]:
        """Render a post by its canonical slug (single path→render code path).

        The post's public path is ``/`` for the home slug, else ``/<slug>`` —
        matching where the writer writes ``var/seo/<slug>.html``. ``language`` is
        not sent: the renderer captures the live SPA, which resolves language
        from the path itself.
        """
        return self.render_path(_public_path_for_slug(slug))


def _public_path_for_slug(slug: Optional[str]) -> str:
    """The public URL path a post's canonical slug resolves to.

    ``/`` for an empty/home slug, else ``/<slug>`` (leading/trailing slashes
    normalised) so it matches the ``var/seo/<slug>.html`` file the writer emits.
    """
    cleaned = (slug or "").strip("/")
    return "/" + cleaned if cleaned else "/"
