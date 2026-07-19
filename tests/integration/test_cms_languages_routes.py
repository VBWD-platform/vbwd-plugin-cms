"""Integration (real PG): the CMS editor-language admin endpoints.

``GET /api/v1/admin/cms/languages/available`` returns the full curated catalog
(admin-gated, so the settings-page dual-list can load its options), and
``GET /api/v1/admin/cms/languages`` returns the RESOLVED enabled list with labels
in configured order (cms.pages.view-gated, consumed by the post editor). Config
is written through the live ``config_store`` (the only writer), so the suite runs
cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest
from flask import current_app

from plugins.cms.src.languages import LANGUAGE_CATALOG


AVAILABLE_URL = "/api/v1/admin/cms/languages/available"
ENABLED_URL = "/api/v1/admin/cms/languages"


@pytest.fixture
def admin_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def set_enabled_languages(db):
    store = current_app.config_store
    saved = dict(store.get_config("cms") or {})

    def _apply(value):
        store.save_config("cms", {**saved, "enabled_languages": value})

    yield _apply
    store.save_config("cms", saved)


def _codes(languages):
    return [language["code"] for language in languages]


# ── /languages/available ────────────────────────────────────────────────────


def test_available_requires_auth(client, db):
    assert client.get(AVAILABLE_URL).status_code == 401


def test_available_returns_full_catalog_for_admin(client, db, admin_headers):
    resp = client.get(AVAILABLE_URL, headers=admin_headers)
    assert resp.status_code == 200
    languages = resp.get_json()["languages"]
    assert languages == LANGUAGE_CATALOG
    assert _codes(languages)[:3] == ["en", "de", "ru"]


# ── /languages (resolved enabled list) ──────────────────────────────────────


def test_enabled_requires_auth(client, db):
    assert client.get(ENABLED_URL).status_code == 401


def test_enabled_reflects_list_value_in_order(
    client, db, admin_headers, set_enabled_languages
):
    set_enabled_languages(["fr", "en"])
    resp = client.get(ENABLED_URL, headers=admin_headers)
    assert resp.status_code == 200
    languages = resp.get_json()["languages"]
    assert _codes(languages) == ["fr", "en"]
    assert languages[0]["label"] == "Français"


def test_enabled_reflects_csv_value(client, db, admin_headers, set_enabled_languages):
    set_enabled_languages("en,de,ja")
    resp = client.get(ENABLED_URL, headers=admin_headers)
    assert _codes(resp.get_json()["languages"]) == ["en", "de", "ja"]


def test_enabled_drops_unknown_codes(client, db, admin_headers, set_enabled_languages):
    set_enabled_languages(["en", "xx", "fr"])
    resp = client.get(ENABLED_URL, headers=admin_headers)
    assert _codes(resp.get_json()["languages"]) == ["en", "fr"]


def test_enabled_empty_falls_back_to_en_de_ru(
    client, db, admin_headers, set_enabled_languages
):
    set_enabled_languages("")
    resp = client.get(ENABLED_URL, headers=admin_headers)
    assert _codes(resp.get_json()["languages"]) == ["en", "de", "ru"]
