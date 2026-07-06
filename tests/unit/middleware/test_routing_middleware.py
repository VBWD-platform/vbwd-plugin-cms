"""Unit tests for CmsRoutingMiddleware."""
from unittest.mock import MagicMock
from flask import Flask

from plugins.cms.src.middleware.routing_middleware import (
    CmsRoutingMiddleware,
    _is_passthrough,
)
from plugins.cms.src.services.routing.matchers import RedirectInstruction


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


# ── _is_passthrough ───────────────────────────────────────────────────────────


def test_is_passthrough_api():
    assert _is_passthrough("/api/v1/cms/posts") is True


def test_is_passthrough_uploads():
    assert _is_passthrough("/uploads/image.png") is True


def test_is_passthrough_regular_path():
    assert _is_passthrough("/my-page") is False


def test_is_passthrough_core_seo_endpoints():
    """S47.1: core robots/sitemap must bypass cms rewrites (else they 404)."""
    assert _is_passthrough("/robots.txt") is True
    assert _is_passthrough("/sitemap.xml") is True
    assert _is_passthrough("/sitemap-1.xml") is True
    assert _is_passthrough("/sitemap-42.xml") is True


def test_is_passthrough_indexnow_key_file():
    """IndexNow key file ``/<key>.txt`` must reach its root route, not be routed.

    Mirrors the nginx location regex ``^/[A-Za-z0-9-]{8,128}\\.txt$`` so a
    catch-all rewrite rule can never shadow the ``indexnow_key_file`` route.
    """
    # A real 32-hex IndexNow key (the reproduced-live case).
    assert _is_passthrough("/a58ccd1812b4da6e72036f9103fb2d65.txt") is True
    # Minimum-length (8-char) and hyphen-bearing keys still pass through.
    assert _is_passthrough("/abcd1234.txt") is True
    assert _is_passthrough("/some-8char-key.txt") is True


def test_is_passthrough_rejects_non_key_txt_paths():
    """Only the strict 8-128 key pattern passes; ordinary slugs are still routed."""
    # Too short (7 chars) — not a key file; must be routed like any slug.
    assert _is_passthrough("/abcdef1.txt") is False
    # A normal page slug is not a passthrough.
    assert _is_passthrough("/some-page") is False
    # A slug that merely ends in .txt but contains a dot/underscore is not the
    # strict key pattern.
    assert _is_passthrough("/my.page.txt") is False
    assert _is_passthrough("/some_page.txt") is False


# ── CmsRoutingMiddleware.before_request ───────────────────────────────────────


def test_middleware_passthrough_api_path():
    """API paths are not routed by middleware."""
    svc = MagicMock()
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/api/v1/cms/posts"):
        result = mw.before_request()
    assert result is None
    svc.evaluate.assert_not_called()


def test_middleware_no_match_returns_none():
    """When evaluate returns None, middleware returns None."""
    svc = MagicMock()
    svc.evaluate.return_value = None
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/my-page"):
        result = mw.before_request()
    assert result is None


def test_middleware_redirect():
    """When evaluate returns a redirect instruction, middleware returns redirect."""
    svc = MagicMock()
    svc.evaluate.return_value = RedirectInstruction(
        location="/home-de",
        code=302,
        is_rewrite=False,
    )
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/"):
        result = mw.before_request()
    assert result is not None
    assert result.status_code == 302
    assert "/home-de" in result.headers.get("Location", "")


def test_middleware_does_not_shadow_indexnow_key_file():
    """A catch-all rewrite must NOT shadow the ``/<key>.txt`` root route.

    Before the passthrough fix, ``before_request`` evaluated the rule and
    returned an ``X-Accel-Redirect`` 200, shadowing ``indexnow_key_file`` so the
    key file served the home page. The path must now pass through untouched
    (``evaluate`` never called).
    """
    svc = MagicMock()
    svc.evaluate.return_value = RedirectInstruction(
        location="/home",
        code=200,
        is_rewrite=True,
    )
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/a58ccd1812b4da6e72036f9103fb2d65.txt"):
        result = mw.before_request()
    assert result is None
    svc.evaluate.assert_not_called()


def test_middleware_rewrite_returns_x_accel():
    """When is_rewrite=True, middleware sets X-Accel-Redirect header."""
    svc = MagicMock()
    svc.evaluate.return_value = RedirectInstruction(
        location="/home-de",
        code=200,
        is_rewrite=True,
    )
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/"):
        result = mw.before_request()
    assert result is not None
    assert result.headers.get("X-Accel-Redirect") == "/home-de"
