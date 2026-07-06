"""Integration: admin geo-block routes (S120, T6), real PG.

Countries are seeded through the ORM/session (no raw SQL). The shared ``db``
fixture builds the schema and rolls each test back.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold local
+ CI); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest
from dependency_injector import providers

from vbwd.models.country import Country
from vbwd.services.filesystem.local import LocalFilesystemManager


GEO_BLOCK_URL = "/api/v1/admin/cms/geo-block"


@pytest.fixture(autouse=True)
def _isolate_geo_block_nginx_writes(app, tmp_path):
    """Keep a successful PUT's nginx-JSON publish out of the real ``var/``.

    A saved geo-block config now (S120.1) regenerates
    ``${VAR_DIR}/cms/nginx/geo-block.json`` via the container filesystem_manager.
    Pin that manager to ``tmp_path`` so these route tests never write the repo
    ``var/`` tree.
    """
    manager = LocalFilesystemManager(var_root=str(tmp_path))
    app.container.filesystem_manager.override(providers.Object(manager))
    try:
        yield
    finally:
        app.container.filesystem_manager.reset_override()


@pytest.fixture
def admin_token(client, db):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    if response.status_code != 200:
        pytest.skip("Admin user not available in test DB")
    data = response.get_json()
    return data.get("token") or data.get("access_token")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _seed_enabled_country(db, code):
    country = Country(code=code, name=f"Country {code}", is_enabled=True, position=1)
    db.session.add(country)
    db.session.flush()
    return country


def test_get_requires_auth(client, db):
    response = client.get(GEO_BLOCK_URL)
    assert response.status_code in (401, 403)


def test_get_returns_config_and_allowed_countries(client, db, auth_headers):
    _seed_enabled_country(db, f"A{uuid.uuid4().hex[:1].upper()}")
    response = client.get(GEO_BLOCK_URL, headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    for key in (
        "is_enabled",
        "bypass_query",
        "bypass_cookie_ttl_days",
        "blocked_target_slug",
        "block_unknown_country",
        "allowed_country_codes",
        "allowed_country_count",
    ):
        assert key in body
    assert isinstance(body["allowed_country_codes"], list)
    assert body["allowed_country_count"] == len(body["allowed_country_codes"])


def test_put_round_trip(client, db, auth_headers):
    response = client.put(
        GEO_BLOCK_URL,
        headers=auth_headers,
        json={
            "is_enabled": True,
            "bypass_query": "?allowme=yes",
            "bypass_cookie_ttl_days": 14,
            "blocked_target_slug": "/locked",
            "block_unknown_country": True,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_enabled"] is True
    assert body["bypass_query"] == "allowme=yes"  # normalized
    assert body["bypass_cookie_ttl_days"] == 14
    assert body["block_unknown_country"] is True

    fetched = client.get(GEO_BLOCK_URL, headers=auth_headers).get_json()
    assert fetched["is_enabled"] is True
    assert fetched["bypass_query"] == "allowme=yes"


def test_put_rejects_bad_bypass_query(client, db, auth_headers):
    response = client.put(
        GEO_BLOCK_URL, headers=auth_headers, json={"bypass_query": "a=1&b=2"}
    )
    assert response.status_code == 400


def test_put_rejects_non_positive_ttl(client, db, auth_headers):
    response = client.put(
        GEO_BLOCK_URL,
        headers=auth_headers,
        json={"bypass_cookie_ttl_days": 0},
    )
    assert response.status_code == 400


def test_put_rejects_bad_slug(client, db, auth_headers):
    response = client.put(
        GEO_BLOCK_URL,
        headers=auth_headers,
        json={"blocked_target_slug": "locked"},
    )
    assert response.status_code == 400
