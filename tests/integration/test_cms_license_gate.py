"""Integration (real PG): the ``cms`` license gate blocks CMS routes with 402.

The S135 license-blockage demo: when licensing is ENFORCED
(``LICENSE_REQUIRED=true``) and no held key's scope covers ``cms``, every CMS
route — the fe-admin admin surface AND the public fe-user render surface —
returns **402 Payment Required**. When licensing is off (the CE default,
``LICENSE_REQUIRED=false``) the gate is inert and CMS behaves exactly as today;
with a held key that covers ``cms`` the routes pass through. Non-CMS routes are
never touched — the gate is scoped to the CMS blueprint.

The gate reuses the CORE ``@requires_license(feature="cms")`` decorator's exact
check (LICENSE_REQUIRED inert-path, ``g.license`` resolution, 402 body) via a
blueprint ``before_request`` — so the 402 response is byte-identical to every
other license-gated route in the platform.

Engineering requirements (binding, restated): TDD-first (these are the RED
oracle); DevOps-first (cold local + CI, real PG); SOLID/DI/DRY (one gate, core
check reused — not reimplemented); Liskov (a covering ``has_feature`` context is
swappable for the real one); clean code; no overengineering (blueprint-level
guard, not ~107 per-route decorators). Never edits core — imports the decorator.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest
from flask import current_app


PUBLIC_CONFIG_URL = "/api/v1/cms/config"
ADMIN_CATEGORIES_URL = "/api/v1/admin/cms/categories"
NON_CMS_HEALTH_URL = "/api/v1/health"

LICENSE_REQUIRED_KEY = "LICENSE_REQUIRED"


class _StubLicenseContext:
    """A held-license stand-in: covers exactly the given feature ids."""

    def __init__(self, *covered_features: str) -> None:
        self._covered = set(covered_features)

    def has_feature(self, feature: str) -> bool:
        return feature in self._covered


@pytest.fixture
def admin_token(client, db):
    """Log in as the seeded admin and return the JWT (skips if unavailable)."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    if response.status_code != 200:
        pytest.skip("Admin user not available in test DB")
    data = response.get_json()
    return data.get("token") or data.get("access_token")


@pytest.fixture
def license_state():
    """Set LICENSE_REQUIRED + the app license context, restoring on teardown.

    The session-scoped app boots with LICENSE_REQUIRED=false and a
    ``NullLicenseContext``; each test flips them for its scenario and this
    fixture restores the boot state so no test strands enforcement for another.
    """
    app = current_app._get_current_object()
    saved_required = app.config.get(LICENSE_REQUIRED_KEY, False)
    saved_context = getattr(app, "license_context", None)

    def _apply(*, required: bool, context: object) -> None:
        app.config[LICENSE_REQUIRED_KEY] = required
        app.license_context = context

    yield _apply

    app.config[LICENSE_REQUIRED_KEY] = saved_required
    app.license_context = saved_context


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── CE default: enforcement off → gate inert ─────────────────────────────────


def test_ce_default_public_route_is_not_gated(client, db, license_state):
    """LICENSE_REQUIRED=false → the public CMS config route behaves as today."""
    license_state(required=False, context=_StubLicenseContext())
    assert client.get(PUBLIC_CONFIG_URL).status_code == 200


def test_ce_default_admin_route_is_not_gated(client, db, admin_token, license_state):
    """LICENSE_REQUIRED=false → an admin CMS route is unaffected by the gate."""
    license_state(required=False, context=_StubLicenseContext())
    resp = client.get(ADMIN_CATEGORIES_URL, headers=_auth_header(admin_token))
    assert resp.status_code == 200


# ── Enforced + covered → pass through ────────────────────────────────────────


def test_covered_feature_allows_public_route(client, db, license_state):
    """A held key covering ``cms`` lets the public render route through (200)."""
    license_state(required=True, context=_StubLicenseContext("cms"))
    assert client.get(PUBLIC_CONFIG_URL).status_code == 200


def test_covered_feature_allows_admin_route(client, db, admin_token, license_state):
    """A held key covering ``cms`` lets the admin route through (200)."""
    license_state(required=True, context=_StubLicenseContext("cms"))
    resp = client.get(ADMIN_CATEGORIES_URL, headers=_auth_header(admin_token))
    assert resp.status_code == 200


# ── Enforced + uncovered → 402 for the whole CMS surface ─────────────────────


def test_uncovered_feature_blocks_public_route_with_402(client, db, license_state):
    """No covering key → the public CMS render route returns 402."""
    license_state(required=True, context=_StubLicenseContext())
    assert client.get(PUBLIC_CONFIG_URL).status_code == 402


def test_uncovered_feature_blocks_admin_route_with_402(
    client, db, admin_token, license_state
):
    """No covering key → the admin CMS route returns 402 even when authed."""
    license_state(required=True, context=_StubLicenseContext())
    resp = client.get(ADMIN_CATEGORIES_URL, headers=_auth_header(admin_token))
    assert resp.status_code == 402


def test_402_body_matches_core_decorator_shape(client, db, license_state):
    """The 402 body is the core decorator's verbatim ``error``/``feature`` shape."""
    license_state(required=True, context=_StubLicenseContext())
    resp = client.get(PUBLIC_CONFIG_URL)
    assert resp.status_code == 402
    assert resp.get_json() == {"error": "License required", "feature": "cms"}


def test_uncovered_feature_leaves_non_cms_route_working(client, db, license_state):
    """Only CMS blocks — a non-CMS route still succeeds under enforcement."""
    license_state(required=True, context=_StubLicenseContext())
    assert client.get(NON_CMS_HEALTH_URL).status_code == 200
