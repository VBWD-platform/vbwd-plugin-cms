"""S56.0 unit — editable robots.txt override on the cms ``robots()`` route.

The served ``/robots.txt`` body now honours an admin override:

  * ``seo.mode==off`` still forces ``Disallow: /`` (safety wins, unchanged);
  * else a non-empty ``robots_txt`` cms-config value is served **verbatim**;
  * else the current default template (blocks app surfaces + names sitemap).

These are pure-logic unit tests: a minimal Flask app provides the request
context + a fake ``config_store`` double (no DB), mirroring the plugin's lazy
``current_app.config_store.get_config("cms")`` read.

Engineering requirements (binding, restated): TDD-first (RED before the route
override existed); SOLID/DI/DRY; Liskov (the config read is defensive — a
missing store falls back to the default template); clean code; no
overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest
from flask import Flask

from plugins.cms.src import seo_routes


class _FakeConfigStore:
    def __init__(self, cms_config):
        self._cms_config = cms_config

    def get_config(self, plugin_name):
        return self._cms_config if plugin_name == "cms" else {}


@pytest.fixture
def robots_app():
    app = Flask(__name__)
    app.add_url_rule("/robots.txt", view_func=seo_routes.robots)
    return app


def _robots_body(app, cms_config=None, seo_mode="on"):
    app.config["SEO_MODE"] = seo_mode
    if cms_config is not None:
        app.config_store = _FakeConfigStore(cms_config)
    client = app.test_client()
    return client.get("/robots.txt", base_url="https://example.com").get_data(
        as_text=True
    )


def test_serves_custom_robots_verbatim_when_set(robots_app):
    custom = "User-agent: Googlebot\nDisallow: /secret\n"
    body = _robots_body(robots_app, {"robots_txt": custom})
    assert body == custom


def test_serves_default_template_when_robots_txt_empty(robots_app):
    body = _robots_body(robots_app, {"robots_txt": ""})
    assert "Disallow: /dashboard" in body
    assert "Disallow: /api" in body
    assert "Sitemap:" in body


def test_mode_off_forces_disallow_all_even_with_custom(robots_app):
    body = _robots_body(robots_app, {"robots_txt": "Allow: /"}, seo_mode="off")
    assert "Disallow: /" in body
    assert "Allow: /" not in body


def test_no_config_store_falls_back_to_default(robots_app):
    body = _robots_body(robots_app)
    assert "Disallow: /dashboard" in body
