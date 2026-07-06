"""Integration: geo-block nginx JSON is published on save + via CLI (S120.1, T1).

The admin ``PUT /api/v1/admin/cms/geo-block`` (and the ``flask cms geo-block
sync`` command) must (re)write ``${VAR_DIR}/cms/nginx/geo-block.json`` so the
fe-user nginx njs handler enforces the current config. These tests override the
container's ``filesystem_manager`` with a temp-rooted ``LocalFilesystemManager``
so the write lands in ``tmp_path`` (never the repo ``var/``) and can be read back.

They assert: the file is written on PUT with ``enabled`` reflecting the save;
``allowed_codes`` reflects core enabled countries; a disabled save still writes
``enabled:false``; ``bypass_secret`` is present, stable across two PUTs, and NOT
equal to ``JWT_SECRET_KEY``; and the CLI regenerates the file.

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
WRITTEN_RELATIVE_PATH = "nginx/geo-block.json"


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


@pytest.fixture
def temp_filespace(app, tmp_path):
    """Point the container filesystem_manager at ``tmp_path`` for the test."""
    manager = LocalFilesystemManager(var_root=str(tmp_path))
    app.container.filesystem_manager.override(providers.Object(manager))
    try:
        yield manager.for_plugin("cms")
    finally:
        app.container.filesystem_manager.reset_override()


def _seed_enabled_country(db):
    code = f"Z{uuid.uuid4().hex[:1].upper()}"
    db.session.add(
        Country(code=code, name=f"Country {code}", is_enabled=True, position=1)
    )
    db.session.flush()
    return code


def test_put_enable_writes_geo_block_json(client, db, auth_headers, temp_filespace):
    code = _seed_enabled_country(db)

    response = client.put(
        GEO_BLOCK_URL,
        headers=auth_headers,
        json={
            "is_enabled": True,
            "bypass_query": "allowme=yes",
            "blocked_target_slug": "/locked",
        },
    )
    assert response.status_code == 200

    written = temp_filespace.read_json(WRITTEN_RELATIVE_PATH)
    assert written["enabled"] is True
    assert code in written["allowed_codes"]
    assert written["bypass_query"] == "allowme=yes"
    assert written["blocked_target_slug"] == "/locked"
    assert written["bypass_secret"]


def test_put_disable_still_writes_enabled_false(
    client, db, auth_headers, temp_filespace
):
    response = client.put(
        GEO_BLOCK_URL, headers=auth_headers, json={"is_enabled": False}
    )
    assert response.status_code == 200

    written = temp_filespace.read_json(WRITTEN_RELATIVE_PATH)
    assert written["enabled"] is False


def test_bypass_secret_is_stable_and_not_jwt_secret(
    app, client, db, auth_headers, temp_filespace
):
    first = client.put(GEO_BLOCK_URL, headers=auth_headers, json={"is_enabled": True})
    assert first.status_code == 200
    first_secret = temp_filespace.read_json(WRITTEN_RELATIVE_PATH)["bypass_secret"]

    second = client.put(GEO_BLOCK_URL, headers=auth_headers, json={"is_enabled": True})
    assert second.status_code == 200
    second_secret = temp_filespace.read_json(WRITTEN_RELATIVE_PATH)["bypass_secret"]

    assert first_secret == second_secret
    assert first_secret
    assert first_secret != app.config.get("JWT_SECRET_KEY")


def test_cli_geo_block_sync_regenerates_file(app, db, temp_filespace):
    code = _seed_enabled_country(db)

    result = app.test_cli_runner().invoke(args=["cms", "geo-block", "sync"])

    assert result.exit_code == 0, result.output
    written = temp_filespace.read_json(WRITTEN_RELATIVE_PATH)
    assert code in written["allowed_codes"]
    assert written["bypass_secret"]
