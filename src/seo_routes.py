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
from xml.sax.saxutils import escape, quoteattr

from flask import Response, current_app, request

from plugins.cms.src.routes import cms_bp
from plugins.cms.src.services.seo_registry import aggregate_sitemap_entries

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


def _render_url_element(entry) -> str:
    parts = [f"  <url>\n    <loc>{escape(entry.loc)}</loc>"]
    if entry.lastmod:
        parts.append(f"    <lastmod>{escape(entry.lastmod)}</lastmod>")
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
