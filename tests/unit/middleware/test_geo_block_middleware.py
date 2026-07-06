"""Unit tests for CmsGeoBlockMiddleware behaviour matrix (S120, T5).

The service is a light stub; the token signer is the real HMAC signer so cookie
mint/verify is exercised end-to-end. No DB, no network.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, g

from plugins.cms.src.middleware.geo_block_middleware import (
    BYPASS_COOKIE_NAME,
    CmsGeoBlockMiddleware,
)
from plugins.cms.src.services.geo.bypass_token import GeoBypassTokenSigner


SECRET = "mw-test-secret"


@pytest.fixture
def app():
    application = Flask(__name__)
    application.config["TESTING"] = True
    return application


def _config(**overrides):
    base = dict(
        is_enabled=True,
        bypass_query="",
        bypass_cookie_ttl_days=30,
        blocked_target_slug="/locked",
        block_unknown_country=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _middleware(config, allowed_codes=None):
    service = SimpleNamespace(
        get_config=lambda: config,
        allowed_codes=lambda: set(allowed_codes or []),
    )
    return CmsGeoBlockMiddleware(
        service=service, token_signer=GeoBypassTokenSigner(SECRET)
    )


def _run(app, middleware, path, *, country=None, cookies=None):
    with app.test_request_context(
        path, headers={"Cookie": cookies} if cookies else None
    ):
        g.geoip_country = country
        return middleware.before_request()


def test_disabled_is_noop(app):
    mw = _middleware(_config(is_enabled=False), allowed_codes=[])
    assert _run(app, mw, "/some-page", country="DE") is None


def test_blocked_country_redirects_to_slug(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    result = _run(app, mw, "/some-page", country="DE")
    assert result.status_code == 302
    assert result.headers["Location"] == "/locked"


def test_allowed_country_passes(app):
    mw = _middleware(_config(), allowed_codes=["DE"])
    assert _run(app, mw, "/some-page", country="DE") is None


def test_unknown_country_passes_when_fail_open(app):
    mw = _middleware(_config(block_unknown_country=False), allowed_codes=["DE"])
    assert _run(app, mw, "/some-page", country=None) is None


def test_unknown_country_blocked_when_block_unknown(app):
    mw = _middleware(_config(block_unknown_country=True), allowed_codes=["DE"])
    result = _run(app, mw, "/some-page", country=None)
    assert result.status_code == 302
    assert result.headers["Location"] == "/locked"


def test_passthrough_admin_api_uploads(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    for path in ("/admin/x", "/api/v1/cms/posts", "/uploads/a.png"):
        assert _run(app, mw, path, country="DE") is None


def test_static_assets_pass(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    assert _run(app, mw, "/assets/index-abc.js", country="DE") is None


def test_locked_slug_not_blocked_no_redirect_loop(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    assert _run(app, mw, "/locked", country="DE") is None
    assert _run(app, mw, "/locked/sub", country="DE") is None


def test_bypass_query_sets_cookie_and_strips_param(app):
    mw = _middleware(_config(bypass_query="allowme=yes"), allowed_codes=["AT"])
    result = _run(app, mw, "/page?allowme=yes&keep=1", country="DE")
    assert result.status_code == 302
    assert result.headers["Location"] == "/page?keep=1"
    set_cookie = result.headers["Set-Cookie"]
    assert set_cookie.startswith(f"{BYPASS_COOKIE_NAME}=")
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=2592000" in set_cookie  # 30 days


def test_bypass_query_only_path_when_no_other_params(app):
    mw = _middleware(_config(bypass_query="allowme=yes"), allowed_codes=["AT"])
    result = _run(app, mw, "/page?allowme=yes", country="DE")
    assert result.headers["Location"] == "/page"


def test_valid_bypass_cookie_passes(app):
    token = GeoBypassTokenSigner(SECRET).sign(ttl_days=30)
    mw = _middleware(_config(), allowed_codes=["AT"])
    result = _run(
        app, mw, "/page", country="DE", cookies=f"{BYPASS_COOKIE_NAME}={token}"
    )
    assert result is None


def test_expired_or_tampered_cookie_ignored(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    tampered = f"{BYPASS_COOKIE_NAME}=deadbeef.deadbeef"
    result = _run(app, mw, "/page", country="DE", cookies=tampered)
    assert result.status_code == 302
    assert result.headers["Location"] == "/locked"


def test_block_response_is_no_store(app):
    mw = _middleware(_config(), allowed_codes=["AT"])
    result = _run(app, mw, "/page", country="DE")
    assert result.headers["Cache-Control"] == "private, no-store"


def test_empty_slug_returns_451(app):
    mw = _middleware(_config(blocked_target_slug=""), allowed_codes=["AT"])
    result = _run(app, mw, "/page", country="DE")
    assert result.status_code == 451
    assert result.headers["Cache-Control"] == "private, no-store"


def _raising_config_middleware(exception, session=None):
    """Middleware whose service.get_config() raises (regression: prod outage)."""

    def _raise():
        raise exception

    service = SimpleNamespace(get_config=_raise, allowed_codes=lambda: set())
    return CmsGeoBlockMiddleware(
        service=service,
        token_signer=GeoBypassTokenSigner(SECRET),
        session=session,
    )


def test_config_read_failure_fails_open(app):
    """If get_config raises (e.g. table missing), the request passes through.

    Regression guard: a ProgrammingError from the missing ``cms_geo_block_config``
    table must NOT propagate out of before_request and 500 every request
    (including ``/api/v1/health``), which took the prod API container down.
    """
    from sqlalchemy.exc import ProgrammingError

    error = ProgrammingError("SELECT ...", {}, Exception("UndefinedTable"))
    mw = _raising_config_middleware(error)
    assert _run(app, mw, "/some-page", country="DE") is None


def test_config_read_failure_fails_open_for_any_exception(app):
    mw = _raising_config_middleware(RuntimeError("boom"))
    assert _run(app, mw, "/api/v1/health", country=None) is None


def test_config_read_failure_rolls_back_session(app):
    """The poisoned transaction must be rolled back on the fail-open path.

    Regression guard: a failing ``get_config()`` (e.g. missing
    ``cms_geo_block_config`` table) left the scoped session in an aborted
    transaction (``InFailedSqlTransaction``), so every subsequent query in the
    same request — the currency lookup on ``/api/v1/config`` and the user lookup
    on ``/api/v1/auth/login`` — then 500'd, taking down the whole API. Passing
    through is not enough; the session must be cleaned up.
    """
    session = Mock()
    mw = _raising_config_middleware(RuntimeError("boom"), session=session)

    assert _run(app, mw, "/some-page", country="DE") is None
    session.rollback.assert_called_once_with()


def test_rollback_failure_is_swallowed_and_still_passes_through(app):
    """A failing rollback must not propagate; the request still passes through."""
    session = Mock()
    session.rollback.side_effect = RuntimeError("rollback exploded")
    mw = _raising_config_middleware(RuntimeError("boom"), session=session)

    assert _run(app, mw, "/some-page", country="DE") is None
    session.rollback.assert_called_once_with()
