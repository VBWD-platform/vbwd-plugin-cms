"""S-SEO full-page renderer port — the HTTP adapter that asks an external
renderer for the COMPLETE page HTML (layout + content) so the static SEO file
served to anonymous visitors carries the public layout, not just the content.

Best-effort by contract: a disabled (empty URL) / non-200 / malformed / failed
call returns ``None`` so the writer falls back to the content-only document.
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


def test_empty_url_returns_none_and_makes_no_http_call():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        renderer = HttpFullPageRenderer(prerender_service_url="")
        assert renderer.render_full_page("pricing", "en") is None
        post.assert_not_called()


def test_http_200_with_html_body_returns_text_and_posts_slug_language():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.return_value = _response()
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000/")
        result = renderer.render_full_page("pricing", "en")

    assert result == _FULL_HTML
    post.assert_called_once()
    _args, kwargs = post.call_args
    # The trailing slash is normalised; /prerender is appended.
    assert post.call_args[0][0] == "http://render:9000/prerender"
    assert kwargs["json"] == {"slug": "pricing", "language": "en"}
    assert kwargs["timeout"] == 20


def test_custom_timeout_is_passed_through():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.return_value = _response()
        renderer = HttpFullPageRenderer(
            prerender_service_url="http://render:9000", timeout_seconds=5
        )
        renderer.render_full_page("pricing", None)

    assert post.call_args[1]["timeout"] == 5


def test_non_200_returns_none_and_logs(caplog):
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.return_value = _response(status_code=502, text=_FULL_HTML)
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000")
        with caplog.at_level(logging.WARNING):
            assert renderer.render_full_page("pricing", "en") is None
    assert caplog.records


def test_body_without_html_tag_returns_none():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.return_value = _response(text="just a plain error string")
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000")
        assert renderer.render_full_page("pricing", "en") is None


def test_empty_body_returns_none():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.return_value = _response(text="")
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000")
        assert renderer.render_full_page("pricing", "en") is None


def test_html_tag_match_is_case_insensitive():
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        upper = "<!DOCTYPE HTML><HTML><BODY>X</BODY></HTML>"
        post.return_value = _response(text=upper)
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000")
        assert renderer.render_full_page("pricing", "en") == upper


def test_request_exception_returns_none_and_logs(caplog):
    with patch("plugins.cms.src.services.seo_full_page_renderer.requests.post") as post:
        post.side_effect = RuntimeError("boom")
        renderer = HttpFullPageRenderer(prerender_service_url="http://render:9000")
        with caplog.at_level(logging.WARNING):
            assert renderer.render_full_page("pricing", "en") is None
    assert caplog.records
