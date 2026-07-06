"""cms SEO seam — ``/sitemap.xml`` + ``/robots.txt`` (root-level).

These three routes were core's only SEO endpoints (S47.1); S50.2 moved the
whole SEO feature into cms, the plugin that already owns every ``seo_*``
service. They are registered on ``cms_bp`` with absolute paths, and cms's
``get_url_prefix()`` returns ``""``, so the public URLs stay at the site root
(``/sitemap.xml``, ``/sitemap-<n>.xml``, ``/robots.txt``) — byte-identical to
the pre-move behaviour. The routes talk only to the cms-local
``seo_registry`` aggregator and to Flask config.

Past ``SITEMAP_URL_CAP`` URLs the sitemap becomes an index pointing at numbered
chunk files (``/sitemap-<n>.xml``), as the sitemaps.org protocol requires.
"""
import hmac
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

from flask import Response, current_app, request

from plugins.cms.src.routes import cms_bp
from plugins.cms.src.services.seo_registry import aggregate_sitemap_entries

# The header nginx (increment 2) injects with the shared secret when it routes a
# bot request to the internal render route.
_RENDER_TOKEN_HEADER = "X-VBWD-Render-Token"

# sitemaps.org caps a single sitemap at 50,000 URLs; past that we emit an index.
SITEMAP_URL_CAP = 50000

_DISALLOWED_SURFACES = ("/dashboard", "/api", "/admin")


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


def _xml_response(body: str) -> Response:
    return Response(body, status=200, mimetype="application/xml")


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


def _render_url_element(entry) -> str:
    parts = [f"  <url>\n    <loc>{escape(entry.loc)}</loc>"]
    lastmod = _w3c_lastmod(entry.lastmod)
    if lastmod:
        parts.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
    if entry.changefreq:
        parts.append(f"    <changefreq>{escape(entry.changefreq)}</changefreq>")
    if entry.priority:
        parts.append(f"    <priority>{escape(entry.priority)}</priority>")
    for alternate in entry.alternates:
        hreflang = quoteattr(alternate.get("hreflang", ""))
        href = quoteattr(alternate.get("href", ""))
        parts.append(
            '    <xhtml:link rel="alternate" ' f"hreflang={hreflang} href={href} />"
        )
    parts.append("  </url>")
    return "\n".join(parts)


def _render_urlset(entries) -> str:
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    )
    rows = "\n".join(_render_url_element(entry) for entry in entries)
    if rows:
        rows += "\n"
    return header + rows + "</urlset>\n"


def _render_sitemap_index(chunk_count: int) -> str:
    base = _site_base()
    rows = []
    for index in range(1, chunk_count + 1):
        loc = escape(f"{base}/sitemap-{index}.xml")
        rows.append(f"  <sitemap>\n    <loc>{loc}</loc>\n  </sitemap>")
    body = "\n".join(rows)
    if body:
        body += "\n"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</sitemapindex>\n"
    )


def _chunk(entries, size):
    for start in range(0, len(entries), size):
        yield entries[start : start + size]


@cms_bp.route("/sitemap.xml", methods=["GET"])
def sitemap():
    """Aggregate all providers; emit an index past the URL cap."""
    entries = aggregate_sitemap_entries()
    if len(entries) > SITEMAP_URL_CAP:
        chunk_count = (len(entries) + SITEMAP_URL_CAP - 1) // SITEMAP_URL_CAP
        return _xml_response(_render_sitemap_index(chunk_count))
    return _xml_response(_render_urlset(entries))


@cms_bp.route("/sitemap-<int:chunk>.xml", methods=["GET"])
def sitemap_chunk(chunk: int):
    """Serve the ``chunk``-th 50k-URL slice (1-based)."""
    entries = aggregate_sitemap_entries()
    chunks = list(_chunk(entries, SITEMAP_URL_CAP))
    if chunk < 1 or chunk > len(chunks):
        return _xml_response(_render_urlset([]))
    return _xml_response(_render_urlset(chunks[chunk - 1]))


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
    """
    from plugins.cms.src.services.seo_wiring import (
        build_dynamic_render_service,
        seo_dynamic_render_available,
        seo_render_internal_token,
    )

    token = seo_render_internal_token()
    provided = request.headers.get(_RENDER_TOKEN_HEADER, "")
    if not token or not hmac.compare_digest(provided, token):
        return Response("", status=404)

    if not seo_dynamic_render_available():
        return Response("", status=404)

    path = request.args.get("path") or "/"
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
    """Block app surfaces + name the sitemap; ``seo.mode=off`` blocks all."""
    base = _site_base()
    sitemap_line = f"Sitemap: {base}/sitemap.xml"
    if _seo_mode() == "off":
        body = "User-agent: *\nDisallow: /\n\n" + sitemap_line + "\n"
        return Response(body, status=200, mimetype="text/plain")

    custom = _custom_robots_txt()
    if custom:
        return Response(custom, status=200, mimetype="text/plain")

    lines = ["User-agent: *"]
    lines.extend(f"Disallow: {surface}" for surface in _DISALLOWED_SURFACES)
    lines.append("")
    lines.append(sitemap_line)
    return Response("\n".join(lines) + "\n", status=200, mimetype="text/plain")
