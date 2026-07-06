"""S118 Track B — the internal on-demand render route ``/_seo-render``.

Drives the booted ``client`` (cms enabled ⇒ ``cms_bp`` registered, so the route
is live) and asserts the abuse guard + serving contract:

  * a missing/wrong ``X-VBWD-Render-Token`` ⇒ 404 (the route is not revealed);
  * a valid token + a render hit ⇒ 200 ``text/html`` with the rendered body;
  * a render miss (renderer down) ⇒ 502 so nginx falls back to the SPA shell;
  * the feature switched off ⇒ 404 even with a valid token.

No live Chromium / network: the render client's ``requests.get`` transport is
patched. Config is written through the live ``config_store`` (the only writer).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY; Liskov (a miss degrades to 502, never a 5xx crash);
clean code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
from unittest.mock import MagicMock, patch

from flask import current_app

from plugins.cms.src.services import seo_wiring


RENDER_URL = "/api/v1/cms/_seo-render"
_TOKEN = "s3cr3t-token"
_RENDERED_HTML = (
    '<!doctype html><html lang="en"><head><title>Widget</title></head>'
    "<body><header>NAV</header><main>Widget page</main></body></html>"
)


def _configure(enabled=True, token=_TOKEN, service_url="http://renderer:3000"):
    store = current_app.config_store
    config = store.get_config("cms") or {}
    config["seo_dynamic_render_enabled"] = enabled
    config["seo_render_internal_token"] = token
    config["prerender_service_url"] = service_url
    store.save_config("cms", config)
    # The render cache is a process-wide singleton — clear it so entries from a
    # sibling test never leak into this one.
    seo_wiring._render_cache.clear()


def _http_response(status_code=200, text=_RENDERED_HTML):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


def test_seo_render_requires_internal_token(client, db):
    _configure()
    # No token header at all.
    assert client.get(f"{RENDER_URL}?path=/shop/widget").status_code == 404
    # Wrong token.
    wrong = client.get(
        f"{RENDER_URL}?path=/shop/widget",
        headers={"X-VBWD-Render-Token": "nope"},
    )
    assert wrong.status_code == 404


def test_seo_render_returns_html_on_success(client, db):
    _configure()
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _http_response()
        response = client.get(
            f"{RENDER_URL}?path=/shop/widget",
            headers={"X-VBWD-Render-Token": _TOKEN},
        )

    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert response.get_data(as_text=True) == _RENDERED_HTML


def test_seo_render_502_on_miss(client, db):
    _configure()
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.side_effect = RuntimeError("renderer down")
        response = client.get(
            f"{RENDER_URL}?path=/shop/widget",
            headers={"X-VBWD-Render-Token": _TOKEN},
        )
    assert response.status_code == 502


def test_seo_render_disabled_when_flag_off(client, db):
    _configure(enabled=False)
    response = client.get(
        f"{RENDER_URL}?path=/shop/widget",
        headers={"X-VBWD-Render-Token": _TOKEN},
    )
    assert response.status_code == 404


def test_seo_render_disabled_when_no_service_url(client, db):
    _configure(service_url="")
    response = client.get(
        f"{RENDER_URL}?path=/shop/widget",
        headers={"X-VBWD-Render-Token": _TOKEN},
    )
    assert response.status_code == 404


def test_seo_render_disabled_when_token_empty(client, db):
    _configure(token="")
    # An empty configured token disables the route even if the caller sends one.
    response = client.get(
        f"{RENDER_URL}?path=/shop/widget",
        headers={"X-VBWD-Render-Token": ""},
    )
    assert response.status_code == 404
