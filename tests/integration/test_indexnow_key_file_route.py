"""IndexNow key-file route — ``GET /<key>.txt`` served at the site ROOT.

IndexNow authorizes submitting any URL on the host only when the verification
key file is hosted at the site root (``https://<host>/<key>.txt``). The cms
plugin serves it on ``cms_bp`` (``get_url_prefix()`` == ``""``) exactly like
``/robots.txt`` and ``/sitemap.xml``. The handler returns the configured key as
``text/plain`` ONLY when IndexNow is enabled, the key is non-empty, AND the
requested ``<key>`` matches the configured key; otherwise **404** (so an
arbitrary ``<x>.txt`` is never revealed and the explicit ``/robots.txt`` route
keeps precedence).

Config is written through the live ``config_store`` (the only writer), so the
suite runs cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(mismatch ⇒ 404, never a 500); clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest
from flask import current_app

_KEY = "abcdef0123456789key"


@pytest.fixture
def _reset_indexnow_config():
    """Snapshot + restore the cms config so a test never leaks IndexNow keys."""
    store = current_app.config_store
    before = dict(store.get_config("cms") or {})
    yield store
    store.save_config("cms", before)


def _set_indexnow(store, enabled, key):
    config = store.get_config("cms") or {}
    config["indexnow_enabled"] = enabled
    config["indexnow_key"] = key
    store.save_config("cms", config)


def test_key_file_returns_key_when_enabled_and_matches(client, _reset_indexnow_config):
    _set_indexnow(_reset_indexnow_config, enabled=True, key=_KEY)

    response = client.get(f"/{_KEY}.txt")

    assert response.status_code == 200
    assert "text/plain" in response.content_type
    assert response.get_data(as_text=True) == _KEY


def test_key_file_404_when_key_mismatch(client, _reset_indexnow_config):
    _set_indexnow(_reset_indexnow_config, enabled=True, key=_KEY)

    response = client.get("/some-other-key.txt")

    assert response.status_code == 404


def test_key_file_404_when_disabled(client, _reset_indexnow_config):
    _set_indexnow(_reset_indexnow_config, enabled=False, key=_KEY)

    response = client.get(f"/{_KEY}.txt")

    assert response.status_code == 404


def test_key_file_404_when_key_empty(client, _reset_indexnow_config):
    _set_indexnow(_reset_indexnow_config, enabled=True, key="")

    response = client.get("/.txt")

    assert response.status_code == 404


def test_key_file_not_shadowed_by_catch_all_routing_rule(
    client, db, _reset_indexnow_config
):
    """A live catch-all rewrite rule must not shadow the IndexNow key file.

    Reproduces the production bug: the ``default → /home`` middleware rewrite
    matched ``GET /<key>.txt`` first and returned a 200 with an
    ``X-Accel-Redirect: /home`` header, serving the home page instead of the
    key. With the routing-middleware passthrough fix the request reaches the
    ``indexnow_key_file`` route: 200, ``text/plain`` body == the key, and NO
    ``X-Accel-Redirect`` header.
    """
    from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )

    _set_indexnow(_reset_indexnow_config, enabled=True, key=_KEY)

    catch_all_rewrite = CmsRoutingRule(
        name="catch-all-home",
        is_active=True,
        priority=0,
        match_type="default",
        match_value=None,
        target_slug="/home",
        redirect_code=302,
        is_rewrite=True,
        layer="middleware",
    )
    CmsRoutingRuleRepository(db.session).save(catch_all_rewrite)

    response = client.get(f"/{_KEY}.txt")

    assert response.status_code == 200
    assert "text/plain" in response.content_type
    assert response.get_data(as_text=True) == _KEY
    assert "X-Accel-Redirect" not in response.headers


def test_robots_txt_not_shadowed_by_key_file_route(client, _reset_indexnow_config):
    # Even with IndexNow enabled, the explicit /robots.txt route still wins.
    _set_indexnow(_reset_indexnow_config, enabled=True, key=_KEY)

    response = client.get("/robots.txt")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "User-agent:" in body
    assert body != _KEY
