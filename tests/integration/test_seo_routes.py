"""cms SEO routes — ``/sitemap.xml`` + ``/sitemap-<n>.xml`` + ``/robots.txt``.

Moved from core in S50.2: cms now serves these three root-level routes (on
``cms_bp``, whose ``get_url_prefix()`` is ``""``), byte-identical to the
pre-move core behaviour. These tests drive the booted ``client`` (the cms
plugin is enabled via the manifest, so the routes are registered) and assert:

  * zero providers ⇒ a valid, empty urlset (Liskov null default), not a 500;
  * registered provider entries render with lastmod/changefreq/hreflang;
  * loc values are XML-escaped;
  * past the 50k cap the sitemap becomes an index + numbered chunk files;
  * ``/robots.txt`` blocks the app surfaces and names the sitemap, and
    ``SEO_MODE=off`` disallows everything.

Engineering requirements (binding, restated): TDD-first (these are the route
gate proving cms — not core — serves them); SOLID/DI/DRY; Liskov; clean code;
no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.services import seo_registry
from plugins.cms.src.seo_routes import SITEMAP_URL_CAP


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Run each test against an empty registry, then restore the booted one.

    The app boot registers cms's production provider; these tests need a clean
    slate (or a controlled fake), so snapshot, clear, and restore afterwards.
    """
    saved = seo_registry.list_sitemap_providers()
    seo_registry.clear_sitemap_providers()
    yield
    seo_registry.clear_sitemap_providers()
    for provider in saved:
        seo_registry.register_sitemap_provider(provider)


def _register(entries):
    class Provider:
        def sitemap_entries(self):
            return entries

    seo_registry.register_sitemap_provider(Provider())


def test_sitemap_empty_but_valid_with_no_providers(client):
    """Liskov: zero providers ⇒ a valid, empty urlset (not a 500)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.content_type
    body = response.get_data(as_text=True)
    assert "<urlset" in body
    assert "<url>" not in body


def test_sitemap_lists_provider_entries(client):
    _register(
        [
            seo_registry.SitemapEntry(
                loc="https://x/de/pricing",
                lastmod="2026-01-02T00:00:00+00:00",
                changefreq="weekly",
                priority="0.8",
            )
        ]
    )
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)
    assert "<loc>https://x/de/pricing</loc>" in body
    assert "<lastmod>2026-01-02T00:00:00+00:00</lastmod>" in body
    assert "<changefreq>weekly</changefreq>" in body


def test_sitemap_includes_hreflang_alternates(client):
    _register(
        [
            seo_registry.SitemapEntry(
                loc="https://x/en/pricing",
                alternates=[
                    {"hreflang": "de", "href": "https://x/de/pricing"},
                    {"hreflang": "x-default", "href": "https://x/en/pricing"},
                ],
            )
        ]
    )
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert 'hreflang="de"' in body
    assert 'href="https://x/de/pricing"' in body
    assert 'hreflang="x-default"' in body


def test_sitemap_escapes_loc(client):
    _register([seo_registry.SitemapEntry(loc="https://x/a?b=1&c=2")])
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "&amp;" in body
    assert "b=1&c=2" not in body


def test_sitemap_index_past_cap(client):
    entries = [
        seo_registry.SitemapEntry(loc=f"https://x/p{i}")
        for i in range(SITEMAP_URL_CAP + 1)
    ]
    _register(entries)
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)
    assert "<sitemapindex" in body
    assert "/sitemap-1.xml" in body


def test_sitemap_page_serves_a_chunk(client):
    entries = [
        seo_registry.SitemapEntry(loc=f"https://x/p{i}")
        for i in range(SITEMAP_URL_CAP + 1)
    ]
    _register(entries)
    response = client.get("/sitemap-1.xml")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<urlset" in body


def test_robots_blocks_app_surfaces(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /dashboard" in body
    assert "Disallow: /api" in body
    assert "Disallow: /admin" in body
    assert "Sitemap:" in body
    assert "/sitemap.xml" in body


def test_robots_mode_off_disallows_all(client, app):
    app.config["SEO_MODE"] = "off"
    try:
        body = client.get("/robots.txt").get_data(as_text=True)
        assert "Disallow: /" in body
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        assert "Disallow: /dashboard" not in lines
    finally:
        app.config.pop("SEO_MODE", None)


def test_robots_content_type(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.content_type
