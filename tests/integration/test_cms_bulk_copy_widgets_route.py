"""Integration: POST /admin/cms/widgets/bulk/copy (real PG).

"Make a copy" for CMS widgets: each selected widget is duplicated into a fresh,
inactive row with a collision-safe slug. Widgets have NO owned children.
Unknown ids are skipped. Seeded through the repository (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


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


def _seed_widget(db):
    slug = f"wid-{uuid.uuid4().hex[:8]}"
    widget = CmsWidget(
        slug=slug,
        name="Hero Block",
        widget_type="html",
        content_json={"html": "<p>hi</p>"},
        is_active=True,
    )
    return CmsWidgetRepository(db.session).save(widget)


class TestBulkCopyWidgetsRoute:
    def test_copy_creates_inactive_row(self, client, db, admin_headers):
        widget = _seed_widget(db)
        resp = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": [str(widget.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["count"] == 1
        created = body["items"][0]
        assert created["id"] != str(widget.id)
        assert created["name"] == "Hero Block (Copy)"
        assert created["slug"] == f"{widget.slug}-copy"
        assert created["widget_type"] == "html"
        assert created["content_json"] == {"html": "<p>hi</p>"}
        assert created["is_active"] is False

    def test_copy_same_source_twice_is_collision_safe(self, client, db, admin_headers):
        widget = _seed_widget(db)
        first = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": [str(widget.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        second = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": [str(widget.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        assert first["slug"] == f"{widget.slug}-copy"
        assert second["slug"] == f"{widget.slug}-copy-2"

    def test_unknown_id_is_skipped(self, client, db, admin_headers):
        widget = _seed_widget(db)
        resp = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": [str(uuid.uuid4()), str(widget.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 1

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/widgets/bulk/copy",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
