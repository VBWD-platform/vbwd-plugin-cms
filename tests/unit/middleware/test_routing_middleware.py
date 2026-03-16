"""Unit tests for CmsRoutingMiddleware."""
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask

from plugins.cms.src.middleware.routing_middleware import CmsRoutingMiddleware, _is_passthrough
from plugins.cms.src.services.routing.matchers import RedirectInstruction


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


# ── _is_passthrough ───────────────────────────────────────────────────────────

def test_is_passthrough_api():
    assert _is_passthrough("/api/v1/cms/pages") is True


def test_is_passthrough_uploads():
    assert _is_passthrough("/uploads/image.png") is True


def test_is_passthrough_regular_path():
    assert _is_passthrough("/my-page") is False


# ── CmsRoutingMiddleware.before_request ───────────────────────────────────────

def test_middleware_passthrough_api_path():
    """API paths are not routed by middleware."""
    svc = MagicMock()
    mw = CmsRoutingMiddleware(svc)
    app = _make_app()
    with app.test_request_context("/api/v1/cms/pages"):
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
