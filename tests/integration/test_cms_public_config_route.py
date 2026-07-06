"""Integration (real PG): S120 public CMS config surface exposes ``home_slug``.

The fe-user SPA needs a single source of truth for which CMS slug IS the
homepage, loaded at boot without auth, so ``Home.vue``, the seed, the routing
rule and the prerender can't diverge. This suite proves the public, no-auth
``GET /api/v1/cms/config`` endpoint:

  * returns ``home_slug`` defaulting to ``index`` when nothing is configured;
  * reflects an admin-configured ``home_slug`` from the live cms config blob.

Config is written through the live ``config_store`` (the only writer), so the
suite runs cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (one home for the home-slug default); Liskov (a missing config falls back
to the shipped ``index`` default); clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from flask import current_app


PUBLIC_CONFIG_URL = "/api/v1/cms/config"


def test_home_slug_default_is_index(client, db):
    """With no ``home_slug`` persisted, the public config defaults to ``index``."""
    store = current_app.config_store
    config = dict(store.get_config("cms") or {})
    config.pop("home_slug", None)
    store.save_config("cms", config)

    resp = client.get(PUBLIC_CONFIG_URL)
    assert resp.status_code == 200
    assert resp.get_json()["home_slug"] == "index"


def test_public_config_reflects_configured_home_slug(client, db):
    """A persisted ``home_slug`` is projected onto the public config surface."""
    store = current_app.config_store
    config = dict(store.get_config("cms") or {})
    config["home_slug"] = "welcome"
    store.save_config("cms", config)

    resp = client.get(PUBLIC_CONFIG_URL)
    assert resp.status_code == 200
    assert resp.get_json()["home_slug"] == "welcome"


def test_public_config_needs_no_auth(client, db):
    """The endpoint is public — the SPA reads it anonymously at boot."""
    assert client.get(PUBLIC_CONFIG_URL).status_code == 200
