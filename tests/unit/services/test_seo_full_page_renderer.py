"""S118 Track B — the full-page render HTTP client.

The client calls the self-hosted render service at
``GET <base>/render?path=<url-encoded path>`` and returns the full static HTML
of the fe-user SPA at that path. Best-effort by contract: a disabled (empty
URL) / non-200 / non-HTML / failed call returns ``None`` so the caller falls
back deterministically (the writer to its content-only document, the dynamic
render route to a 502 → SPA shell). No real network — the transport is faked.
"""
import logging
from unittest.mock import MagicMock, patch

from plugins.cms.src.services.seo_full_page_renderer import (
    HttpFullPageRenderer,
)


_FULL_HTML = (
    '<!doctype html><html lang="en"><head><title>X</title></head>'
    "<body><header>NAV</header><main>Body</main></body></html>"
)


def _response(status_code=200, text=_FULL_HTML):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


def test_render_path_builds_correct_url_and_returns_html():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response()
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000/")
        result = renderer.render_path("/shop/product/widget")

    assert result == _FULL_HTML
    get.assert_called_once()
    # The trailing slash is normalised; /render is appended; path is a param
    # (requests URL-encodes it).
    assert get.call_args[0][0] == "http://renderer:3000/render"
    kwargs = get.call_args[1]
    assert kwargs["params"] == {"path": "/shop/product/widget"}
    assert kwargs["timeout"] == 20


def test_render_path_none_when_service_url_empty():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        renderer = HttpFullPageRenderer(prerender_service_url="")
        assert renderer.render_path("/pricing") is None
        get.assert_not_called()


def test_render_path_none_on_non_200(caplog):
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response(status_code=502, text=_FULL_HTML)
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        with caplog.at_level(logging.WARNING):
            assert renderer.render_path("/pricing") is None
    assert caplog.records


def test_render_path_none_on_non_html_body():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response(text="just a plain error string")
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        assert renderer.render_path("/pricing") is None


def test_render_path_none_on_exception(caplog):
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.side_effect = RuntimeError("boom")
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        with caplog.at_level(logging.WARNING):
            assert renderer.render_path("/pricing") is None
    assert caplog.records


def test_render_path_none_on_empty_body():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response(text="")
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        assert renderer.render_path("/pricing") is None


def test_render_path_html_marker_is_case_insensitive():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        upper = "<!DOCTYPE HTML><HTML><BODY>X</BODY></HTML>"
        get.return_value = _response(text=upper)
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        assert renderer.render_path("/pricing") == upper


def test_render_path_custom_timeout_is_passed_through():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response()
        renderer = HttpFullPageRenderer(
            prerender_service_url="http://renderer:3000", timeout_seconds=5
        )
        renderer.render_path("/pricing")
    assert get.call_args[1]["timeout"] == 5


# ── render_full_page (writer call site) derives the path and delegates ────────


def test_render_full_page_delegates_to_render_path_with_slug_path():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response()
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        assert renderer.render_full_page("pricing", "en") == _FULL_HTML
    assert get.call_args[1]["params"] == {"path": "/pricing"}


def test_render_full_page_empty_slug_maps_to_root_path():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.get") as get:
        get.return_value = _response()
        renderer = HttpFullPageRenderer(prerender_service_url="http://renderer:3000")
        renderer.render_full_page("", None)
    assert get.call_args[1]["params"] == {"path": "/"}
