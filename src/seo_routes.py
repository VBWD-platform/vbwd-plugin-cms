"""cms SEO seam — ``/sitemap.xml`` + ``/robots.txt`` (root-level).

These three routes were core's only SEO endpoints (S47.1); S50.2 moved the
whole SEO feature into cms, the plugin that already owns every ``seo_*``
service. They are registered on ``cms_bp`` with absolute paths, and cms's
``get_url_prefix()`` returns ``""``, so the public URLs stay at the site root.
The routes talk only to the cms-local ``seo_registry`` and to Flask config.

Sitemap URL scheme (S154 P1, registry v2):
  * ``/sitemap.xml`` — ALWAYS a ``<sitemapindex>`` listing every provider's
    chunk files, built from provider ``count()``s only;
  * ``/sitemap-<name>-<n>.xml`` — ONE ``<urlset>`` of at most
    ``SITEMAP_URL_CAP`` URLs from ``provider.page((n-1)*cap, cap)``; an unknown
    provider or out-of-range ``n`` is a 404;
  * ``/sitemap-<n>.xml`` — the pre-S154 numbering (already submitted to Search
    Console): serves the n-th chunk of the index in place (200, no redirect).
"""
import hmac
from datetime import datetime, timezone
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from flask import Response, current_app, request

from plugins.cms.src.routes import cms_bp
from plugins.cms.src.services.seo_registry import list_sitemap_providers
from plugins.cms.src.services.seo_robots_policy import build_default_robots_txt
from plugins.cms.src.services.seo_sitemap_chunks import (
    SITEMAP_URL_CAP,
    SitemapChunker,
    SitemapChunkRef,
)

# The header nginx (increment 2) injects with the shared secret when it routes a
# bot request to the internal render route.
_RENDER_TOKEN_HEADER = "X-VBWD-Render-Token"

# Sitemaps change at most as often as content; let crawlers/proxies reuse them.
SITEMAP_CACHE_CONTROL = "public, max-age=3600"
SITEMAP_CONTENT_TYPE = "application/xml; charset=utf-8"


def _seo_mode() -> str:
    """Resolve the SEO mode (``on``/``off``) from Flask config, default ``on``."""
    return str(current_app.config.get("SEO_MODE", "on")).lower()


def _custom_robots_txt() -> str:
    """The admin-editable robots.txt override (S56), or ``""`` when unset.

    Read lazily/defensively from the cms config store (the same blob as
    ``seo_prerender_enabled``); any missing store/key yields ``""`` so the
    route falls back to its default template.
    """
    config_store = getattr(current_app, "config_store", None)
    if config_store is None:
        return ""
    cfg = config_store.get_config("cms") or {}
    value = cfg.get("robots_txt", "")
    return value if isinstance(value, str) else ""


def _public_base_url() -> str:
    """The admin-configured canonical site root, or ``""`` when unset.

    Read lazily from the cms config store (the same ``public_base_url`` the
    sitemap ``<loc>`` provider + RSS feed already use); any missing store/key
    yields ``""`` so callers fall back to the request host.
    """
    config_store = getattr(current_app, "config_store", None)
    if config_store is None:
        return ""
    cfg = config_store.get_config("cms") or {}
    value = cfg.get("public_base_url", "")
    return value if isinstance(value, str) else ""


def _site_base() -> str:
    """Canonical absolute site root (no trailing slash) for cross-links.

    Prefers the configured ``public_base_url`` so ``robots.txt`` and the
    sitemap index emit the canonical **https** scheme — the backend sits behind
    a TLS-terminating proxy chain that delivers ``request.host_url`` as plain
    ``http``. Falls back to the request host when unconfigured (dev/tests).
    """
    base = _public_base_url().rstrip("/")
    return base or request.host_url.rstrip("/")


def _sitemap_response(body: str) -> Response:
    """A cacheable XML sitemap response; an ``If-None-Match`` hit yields 304."""
    response = Response(body, status=200, content_type=SITEMAP_CONTENT_TYPE)
    response.headers["Cache-Control"] = SITEMAP_CACHE_CONTROL
    response.add_etag()
    response.make_conditional(request)
    return response


def _w3c_lastmod(value):
    """Coerce a provider ``lastmod`` to valid W3C Datetime, or drop it.

    Google's Sitemaps report treats the whole file as unreadable when a
    ``lastmod`` gives a time without a timezone, carries sub-second precision,
    or is otherwise malformed. Prod ``cms_post.updated_at`` is naive, so its
    ``.isoformat()`` (``...Thh:mm:ss.ffffff``, no zone) is exactly that. We
    normalise every entry at this single render choke point:

      * a parseable naive datetime -> assume UTC, drop micros, append ``Z``;
      * a parseable aware datetime -> keep the offset, drop micros;
      * a bare ``YYYY-MM-DD`` date -> pass through (already valid);
      * anything unparseable       -> ``None`` so ``<lastmod>`` is omitted.
    """
    if not value:
        return None
    text = value.strip()
    # A bare date is valid W3C Datetime on its own; keep it verbatim.
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return text
        except ValueError:
            return None
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    parsed = parsed.replace(microsecond=0)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return parsed.isoformat()


def _absolute_url(url: str, site_base: str) -> str:
    """Join a root-relative URL with ``site_base``; absolute URLs pass through.

    sitemaps.org requires fully-qualified ``<loc>``s, but a provider without a
    request (``public_base_url`` unset) can only emit ``/<path>``.
    """
    if urlsplit(url).scheme:
        return url
    return f"{site_base}/{url.lstrip('/')}"


def _render_url_element(entry, site_base: str) -> str:
    loc = _absolute_url(entry.loc, site_base)
    parts = [f"  <url>\n    <loc>{escape(loc)}</loc>"]
    lastmod = _w3c_lastmod(entry.lastmod)
    if lastmod:
        parts.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
    if entry.changefreq:
        parts.append(f"    <changefreq>{escape(entry.changefreq)}</changefreq>")
    if entry.priority:
        parts.append(f"    <priority>{escape(entry.priority)}</priority>")
    for alternate in entry.alternates:
        hreflang = quoteattr(alternate.get("hreflang", ""))
        href = quoteattr(_absolute_url(alternate.get("href", ""), site_base))
        parts.append(
            '    <xhtml:link rel="alternate" ' f"hreflang={hreflang} href={href} />"
        )
    parts.append("  </url>")
    return "\n".join(parts)


def _render_urlset(entries, site_base: str) -> str:
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    )
    rows = "\n".join(_render_url_element(entry, site_base) for entry in entries)
    if rows:
        rows += "\n"
    return header + rows + "</urlset>\n"


def _render_sitemap_index(chunk_refs) -> str:
    base = _site_base()
    rows = []
    for chunk_ref in chunk_refs:
        loc = escape(f"{base}/{chunk_ref.filename}")
        rows.append(f"  <sitemap>\n    <loc>{loc}</loc>\n  </sitemap>")
    body = "\n".join(rows)
    if body:
        body += "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</sitemapindex>\n"
    )


def _sitemap_chunker() -> SitemapChunker:
    """A chunker over the live providers + the live private path prefixes."""
    from plugins.cms.src.services.seo_wiring import seo_private_path_prefixes

    return SitemapChunker(
        list_sitemap_providers(),
        private_path_prefixes=seo_private_path_prefixes(),
        url_cap=SITEMAP_URL_CAP,
    )


def _chunk_response(chunker: SitemapChunker, chunk_ref: SitemapChunkRef) -> Response:
    entries = chunker.chunk_entries(chunk_ref.provider_name, chunk_ref.number)
    if entries is None:
        return Response("", status=404)
    return _sitemap_response(_render_urlset(entries, _site_base()))


@cms_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """The sitemap index: one ``<sitemap>`` per provider chunk (counts only)."""
    return _sitemap_response(_render_sitemap_index(_sitemap_chunker().chunk_refs()))


@cms_bp.route("/sitemap-<provider_name>-<int:chunk_number>.xml", methods=["GET"])
def sitemap_provider_chunk(provider_name: str, chunk_number: int):
    """Serve chunk ``chunk_number`` (1-based) of provider ``provider_name``."""
    chunk_ref = SitemapChunkRef(provider_name, chunk_number)
    return _chunk_response(_sitemap_chunker(), chunk_ref)


@cms_bp.route("/sitemap-<int:chunk>.xml", methods=["GET"])
def sitemap_chunk(chunk: int):
    """Pre-S154 numbering: serve the ``chunk``-th (1-based) chunk of the index."""
    chunker = _sitemap_chunker()
    chunk_ref = chunker.legacy_chunk_ref(chunk)
    if chunk_ref is None:
        return Response("", status=404)
    return _chunk_response(chunker, chunk_ref)


@cms_bp.route("/api/v1/cms/_seo-render", methods=["GET"])
def seo_dynamic_render():
    """GET /_seo-render?path=… — on-demand full-page render for the nginx bot branch.

    Renders (or serves from cache) the full static HTML of the fe-user SPA at
    ``path``. On a render miss it returns **502** so nginx falls back to the SPA
    shell (the site never 5xx's on a render miss).

    Abuse guard: triggering headless renders from a public URL is a DoS vector,
    so the route requires the ``X-VBWD-Render-Token`` shared secret (injected by
    nginx). A missing/wrong token — or an empty configured token, or the feature
    switched off / no renderer URL — returns **404** (the route is not revealed).

    A path under a private prefix (``seo_private_path_prefixes``: ``/dashboard``,
    ``/tuktuk``, ``/pay``) is never rendered for bots: **404**, so
    nginx falls back to its noindex-tagged shell instead of an indexable page.
    """
    from plugins.cms.src.services.seo_wiring import (
        build_dynamic_render_service,
        seo_dynamic_render_available,
        seo_render_internal_token,
        seo_render_path_is_private,
    )

    token = seo_render_internal_token()
    provided = request.headers.get(_RENDER_TOKEN_HEADER, "")
    if not token or not hmac.compare_digest(provided, token):
        return Response("", status=404)

    if not seo_dynamic_render_available():
        return Response("", status=404)

    path = request.args.get("path") or "/"
    if seo_render_path_is_private(path):
        return Response("", status=404)
    html = build_dynamic_render_service().render(path)
    if html is None:
        return Response("", status=502)
    return Response(html, status=200, mimetype="text/html")


def _indexnow_key_config() -> tuple:
    """Resolve the IndexNow (enabled, key) pair from the live cms config.

    Read lazily/defensively from the same cms config blob the other SEO
    settings use; a missing store/key yields ``(False, "")`` so the key-file
    route 404s (feature off).
    """
    config_store = getattr(current_app, "config_store", None)
    if config_store is None:
        return (False, "")
    cfg = config_store.get_config("cms") or {}
    enabled = bool(cfg.get("indexnow_enabled", False))
    key = cfg.get("indexnow_key", "")
    return (enabled, key if isinstance(key, str) else "")


@cms_bp.route("/<key>.txt", methods=["GET"])
def indexnow_key_file(key: str):
    """GET /<key>.txt — the IndexNow verification file, served at the site root.

    IndexNow authorizes submitting any URL on the host only when the key file is
    hosted at the site root, so this lives on ``cms_bp`` (prefix ``""``) beside
    ``/robots.txt`` + ``/sitemap.xml``. The body is exactly the configured key,
    returned as ``text/plain`` ONLY when IndexNow is enabled, the key is
    non-empty, AND the requested ``<key>`` matches it; otherwise **404** (so an
    arbitrary ``<x>.txt`` is never revealed and the explicit ``/robots.txt`` /
    ``/sitemap.xml`` routes keep precedence).
    """
    enabled, configured_key = _indexnow_key_config()
    if not enabled or not configured_key or key != configured_key:
        return Response("", status=404)
    return Response(configured_key, status=200, mimetype="text/plain")


@cms_bp.route("/robots.txt", methods=["GET"])
def robots():
    """Serve ``seo.mode=off`` block-all, else the admin override, else the default.

    The default policy (S150) lives in ``seo_robots_policy``: CMS content stays
    crawlable, only the private surfaces are disallowed.
    """
    base = _site_base()
    if _seo_mode() == "off":
        body = f"User-agent: *\nDisallow: /\n\nSitemap: {base}/sitemap.xml\n"
        return Response(body, status=200, mimetype="text/plain")

    custom = _custom_robots_txt()
    if custom:
        return Response(custom, status=200, mimetype="text/plain")

    return Response(build_default_robots_txt(base), status=200, mimetype="text/plain")
