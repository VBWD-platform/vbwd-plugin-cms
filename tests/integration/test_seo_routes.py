"""cms SEO routes — ``/sitemap.xml`` + ``/sitemap-<name>-<n>.xml`` + ``/robots.txt``.

Moved from core in S50.2: cms serves these root-level routes (on ``cms_bp``,
whose ``get_url_prefix()`` is ``""``). S154 P1 (registry v2, D1/D2) makes the
sitemap scale to millions of URLs. These tests drive the booted ``client``:

  * ``/sitemap.xml`` is ALWAYS a sitemap index of per-provider chunk files
    ``/sitemap-<name>-<n>.xml``, built from ``count()`` alone (no paging);
  * a chunk renders ONE ``provider.page((n-1)*cap, cap)`` call as a urlset;
    an unknown provider or an out-of-range ``n`` is a 404;
  * legacy list-style providers still appear (adapter, Liskov);
  * private paths are filtered centrally for every provider;
  * the pre-S154 ``/sitemap-<n>.xml`` (submitted to Search Console) still
    serves the n-th chunk of the index;
  * ``/robots.txt`` blocks only the private surfaces (S150) and names
    ``/sitemap.xml``; ``SEO_MODE=off`` disallows everything.

Engineering requirements (binding, restated): TDD-first (these are the route
gate proving cms — not core — serves them); SOLID/DI/DRY; Liskov; clean code;
no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re

import pytest

from plugins.cms.src.services import seo_registry
from plugins.cms.src.seo_routes import SITEMAP_URL_CAP

LARGE_PROVIDER_SIZE = 120000


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
    """Register a LEGACY list-style provider (adapted, named ``provider``)."""

    class Provider:
        def sitemap_entries(self):
            return entries

    seo_registry.register_sitemap_provider(Provider())


class _RecordingProvider:
    """A v2 provider reporting ``size`` URLs; generates only the asked page."""

    def __init__(self, name, size):
        self.name = name
        self._size = size
        self.page_calls = []

    def count(self):
        return self._size

    def page(self, offset, limit):
        self.page_calls.append((offset, limit))
        stop = min(offset + limit, self._size)
        return (
            seo_registry.SitemapEntry(loc=f"https://x/{self.name}/{index}")
            for index in range(offset, stop)
        )


def _locs(body):
    return re.findall(r"<loc>(.*?)</loc>", body)


def test_sitemap_index_is_empty_but_valid_with_no_providers(client):
    """Liskov: zero providers ⇒ a valid, empty sitemap index (not a 500)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.content_type
    body = response.get_data(as_text=True)
    assert "<sitemapindex" in body
    assert "<sitemap>" not in body


def test_sitemap_index_lists_chunks_of_a_large_provider_without_paging(client):
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    seo_registry.register_sitemap_provider(provider)

    body = client.get("/sitemap.xml").get_data(as_text=True)

    assert "<sitemapindex" in body
    assert [loc.rsplit("/", 1)[-1] for loc in _locs(body)] == [
        "sitemap-fake-1.xml",
        "sitemap-fake-2.xml",
        "sitemap-fake-3.xml",
    ]
    assert provider.page_calls == []


def test_provider_chunk_pages_exactly_once(client):
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    seo_registry.register_sitemap_provider(provider)

    response = client.get("/sitemap-fake-2.xml")

    assert response.status_code == 200
    assert provider.page_calls == [(SITEMAP_URL_CAP, SITEMAP_URL_CAP)]
    body = response.get_data(as_text=True)
    assert body.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<urlset" in body and body.rstrip().endswith("</urlset>")
    locs = _locs(body)
    assert len(locs) == SITEMAP_URL_CAP
    assert locs[0] == f"https://x/fake/{SITEMAP_URL_CAP}"


@pytest.mark.parametrize(
    "path", ["/sitemap-fake-0.xml", "/sitemap-fake-4.xml", "/sitemap-unknown-1.xml"]
)
def test_unknown_or_out_of_range_chunk_is_404(client, path):
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    seo_registry.register_sitemap_provider(provider)
    assert client.get(path).status_code == 404
    assert provider.page_calls == []


def test_sitemap_responses_are_cacheable_xml(client):
    _register([seo_registry.SitemapEntry(loc="https://x/a")])
    for path in ("/sitemap.xml", "/sitemap-provider-1.xml"):
        response = client.get(path)
        assert response.headers["Content-Type"] == "application/xml; charset=utf-8"
        assert response.headers["Cache-Control"] == "public, max-age=3600"
        assert response.headers.get("ETag")
        revalidated = client.get(
            path, headers={"If-None-Match": response.headers["ETag"]}
        )
        assert revalidated.status_code == 304


def test_legacy_provider_entries_render_in_its_chunk(client):
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
    index_body = client.get("/sitemap.xml").get_data(as_text=True)
    assert any(loc.endswith("/sitemap-provider-1.xml") for loc in _locs(index_body))

    body = client.get("/sitemap-provider-1.xml").get_data(as_text=True)
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
    body = client.get("/sitemap-provider-1.xml").get_data(as_text=True)
    assert 'hreflang="de"' in body
    assert 'href="https://x/de/pricing"' in body
    assert 'hreflang="x-default"' in body


def test_sitemap_escapes_loc(client):
    _register([seo_registry.SitemapEntry(loc="https://x/a?b=1&c=2")])
    body = client.get("/sitemap-provider-1.xml").get_data(as_text=True)
    assert "&amp;" in body
    assert "b=1&c=2" not in body


def test_private_paths_are_filtered_for_every_provider(client):
    _register(
        [
            seo_registry.SitemapEntry(loc="https://x/dashboard/orders"),
            seo_registry.SitemapEntry(loc="/pay"),
            seo_registry.SitemapEntry(loc="https://x/payments-guide"),
        ]
    )
    locs = _locs(client.get("/sitemap-provider-1.xml").get_data(as_text=True))
    assert locs == ["https://x/payments-guide"]


def test_legacy_numbered_chunk_serves_the_nth_index_chunk(client):
    """``/sitemap-1.xml`` (submitted to Search Console pre-S154) keeps working."""
    _register([seo_registry.SitemapEntry(loc="https://x/a")])
    seo_registry.register_sitemap_provider(
        _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    )

    first = client.get("/sitemap-1.xml")
    assert first.status_code == 200
    assert first.get_data() == client.get("/sitemap-provider-1.xml").get_data()

    third = client.get("/sitemap-3.xml")
    assert _locs(third.get_data(as_text=True))[0] == (
        f"https://x/fake/{SITEMAP_URL_CAP}"
    )
    assert client.get("/sitemap-5.xml").status_code == 404


def test_robots_blocks_app_surfaces(client):
    lines = client.get("/robots.txt").get_data(as_text=True).splitlines()
    assert "Allow: /api/v1/cms/" in lines
    assert "Disallow: /api/" in lines
    assert "Disallow: /admin/" in lines
    assert "Disallow: /dashboard$" in lines
    assert "Disallow: /dashboard/" in lines
    for bare_prefix in ("Disallow: /api", "Disallow: /admin", "Disallow: /dashboard"):
        assert bare_prefix not in lines
    assert any(
        line.startswith("Sitemap: ") and line.endswith("/sitemap.xml") for line in lines
    )


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
