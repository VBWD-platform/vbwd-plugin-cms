"""The default ``robots.txt`` policy (S150): CMS content is always crawlable.

One ``User-agent: *`` group that allows the whole site, re-allows the public
CMS read API under the otherwise-private ``/api/`` tree (RFC 9309 longest
match: ``/api/v1/cms/`` beats ``/api/``), and disallows only the private
surfaces. Trailing slashes and the ``$`` end anchor keep CMS slugs such as
``/admin-guide`` or ``/dashboard-tips`` crawlable.

Pure: the caller passes the site base, so this is testable without Flask.
The ``seo_routes.robots()`` route decides *which* body to serve (``seo.mode=off``
/ admin override / this default).
"""

# Public read APIs under /api/ that JS-rendering crawlers must fetch to see
# the content the SPA renders.
CRAWLABLE_API_PREFIXES = ("/api/v1/cms/",)

# The only surfaces hidden from robots by default.
PRIVATE_SURFACES = ("/api/", "/admin/", "/dashboard$", "/dashboard/")


def build_default_robots_txt(site_base: str) -> str:
    """Return the default ``robots.txt`` body naming ``<site_base>/sitemap.xml``."""
    lines = ["User-agent: *", "Allow: /"]
    lines.extend(f"Allow: {prefix}" for prefix in CRAWLABLE_API_PREFIXES)
    lines.extend(f"Disallow: {surface}" for surface in PRIVATE_SURFACES)
    lines.append("")
    lines.append(f"Sitemap: {site_base.rstrip('/')}/sitemap.xml")
    return "\n".join(lines) + "\n"
