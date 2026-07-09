"""Integration: POST /admin/cms/styles/bulk/copy (real PG).

"Make a copy" for CMS styles: each selected style is duplicated into a fresh,
inactive, non-default row whose slug is collision-safe ("<base>-copy",
"-copy-2", …). Unknown ids are skipped, not fatal. Styles have NO owned
children. Seeded through the repository (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_style import CmsStyle
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository


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


def _seed_style(db, base):
    slug = f"{base}-{uuid.uuid4().hex[:8]}"
    style = CmsStyle(
        slug=slug,
        name="My Style",
        source_css=".x{color:red}",
        is_active=True,
        is_default=True,
    )
    return CmsStyleRepository(db.session).save(style)


class TestBulkCopyStylesRoute:
    def test_copy_creates_inactive_non_default_row(self, client, db, admin_headers):
        style = _seed_style(db, "sty")
        resp = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": [str(style.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["count"] == 1
        created = body["items"][0]
        assert created["id"] != str(style.id)
        assert created["name"] == "My Style (Copy)"
        assert created["slug"] == f"{style.slug}-copy"
        assert created["source_css"] == ".x{color:red}"
        assert created["is_active"] is False
        assert created["is_default"] is False

    def test_copy_same_source_twice_is_collision_safe(self, client, db, admin_headers):
        style = _seed_style(db, "sty")
        first = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": [str(style.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        second = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": [str(style.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        assert first["slug"] == f"{style.slug}-copy"
        assert second["slug"] == f"{style.slug}-copy-2"

    def test_unknown_id_is_skipped(self, client, db, admin_headers):
        style = _seed_style(db, "sty")
        resp = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": [str(uuid.uuid4()), str(style.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 1

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": "nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/styles/bulk/copy",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
