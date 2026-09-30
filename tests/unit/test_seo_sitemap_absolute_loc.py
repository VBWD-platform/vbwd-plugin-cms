"""S150 unit — every sitemap ``<loc>`` (and hreflang ``href``) is absolute.

sitemaps.org requires fully-qualified URLs and Google rejects relative ones.
With ``public_base_url`` unset, the cms provider (which has no request) emits
root-relative paths (``/about``). The render layer is the single choke point
with a request, so it joins relative URLs with the site base there:

  * ``public_base_url`` unset  -> ``scheme://host[:port]`` of the request;
  * ``public_base_url`` set    -> that base (trailing slash stripped, no ``//``);
  * already-absolute URLs      -> unchanged.

Engineering requirements (binding, restated): TDD-first (RED before the join
existed); SOLID (one render choke point); DI (the provider is swapped via
monkeypatch, no DB); DRY; Liskov; clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re

import pytest
from flask import Flask

from plugins.cms.src import seo_routes
from plugins.cms.src.services.seo_registry import SitemapEntry

SMALL_URL_CAP = 2


class _FakeConfigStore:
    def __init__(self, cms_config):
        self._cms_config = cms_config

    def get_config(self, plugin_name):
        return self._cms_config if plugin_name == "cms" else {}


def _entries():
    return [
        SitemapEntry(
            loc="/about",
            alternates=[
                {"hreflang": "en", "href": "/about"},
                {"hreflang": "x-default", "href": "/about"},
            ],
        ),
        SitemapEntry(loc="/"),
        SitemapEntry(loc="https://canonical.example.org/kept"),
    ]


@pytest.fixture
def sitemap_app(monkeypatch):
    monkeypatch.setattr(seo_routes, "aggregate_sitemap_entries", _entries)
    app = Flask(__name__)
    app.add_url_rule("/sitemap.xml", view_func=seo_routes.sitemap)
    app.add_url_rule("/sitemap-<int:chunk>.xml", view_func=seo_routes.sitemap_chunk)
    return app


def _get(app, path, public_base_url=""):
    app.config_store = _FakeConfigStore({"public_base_url": public_base_url})
    response = app.test_client().get(path, headers={"Host": "localhost:8080"})
    return response.get_data(as_text=True)


def _urls(body):
    return re.findall(r"<loc>(.*?)</loc>", body) + re.findall(r'href="(.*?)"', body)


def test_relative_locs_use_request_host_with_port(sitemap_app):
    urls = _urls(_get(sitemap_app, "/sitemap.xml"))
    assert "http://localhost:8080/about" in urls
    assert "http://localhost:8080/" in urls
    relative = [url for url in urls if not url.startswith("http")]
    assert relative == []


def test_relative_locs_use_public_base_url_without_double_slash(sitemap_app):
    body = _get(sitemap_app, "/sitemap.xml", public_base_url="https://example.com/")
    urls = _urls(body)
    assert "https://example.com/about" in urls
    assert "https://example.com/" in urls
    assert all("example.com//" not in url for url in urls)


def test_absolute_loc_passes_through_unchanged(sitemap_app):
    urls = _urls(_get(sitemap_app, "/sitemap.xml"))
    assert "https://canonical.example.org/kept" in urls


def test_chunk_and_index_locs_are_absolute(sitemap_app, monkeypatch):
    monkeypatch.setattr(seo_routes, "SITEMAP_URL_CAP", SMALL_URL_CAP)
    index_urls = _urls(_get(sitemap_app, "/sitemap.xml"))
    assert index_urls == [
        "http://localhost:8080/sitemap-1.xml",
        "http://localhost:8080/sitemap-2.xml",
    ]
    chunk_urls = _urls(_get(sitemap_app, "/sitemap-1.xml"))
    assert chunk_urls
    assert all(url.startswith("http://localhost:8080/") for url in chunk_urls)
