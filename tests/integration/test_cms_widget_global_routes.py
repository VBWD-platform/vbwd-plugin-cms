"""Integration: the site-wide (global) widget feature is removed, real PG.

The ``is_global`` widget injection was the wrong approach and is dropped
entirely. These tests pin the removal end-to-end:

* ``GET /api/v1/cms/widgets/global`` no longer exists (404).
* the admin create/update routes ignore an ``is_global`` in the body — they do
  not crash and do not echo/persist the field.

Data is seeded through repositories (no raw SQL); the shared ``db`` fixture
creates + drops the test DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


@pytest.fixture(autouse=True)
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


def _save_widget(db, *, slug, is_active=True):
    widget = CmsWidget(
        slug=slug,
        name=slug,
        widget_type="html",
        content_json={"content": ""},
        is_active=is_active,
    )
    CmsWidgetRepository(db.session).save(widget)
    return widget


class TestGlobalWidgetsEndpointRemoved:
    def test_global_endpoint_is_gone(self, client, db):
        response = client.get("/api/v1/cms/widgets/global")
        assert response.status_code == 404


class TestAdminIgnoresIsGlobal:
    def test_update_ignores_is_global_in_body(self, client, db, auth_headers):
        widget = _save_widget(db, slug=f"w-{uuid.uuid4().hex[:8]}")

        response = client.put(
            f"/api/v1/admin/cms/widgets/{widget.id}",
            json={"is_global": True, "name": "Renamed"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "is_global" not in response.get_json()

        db.session.expire_all()
        reloaded = CmsWidgetRepository(db.session).find_by_id(str(widget.id))
        assert not hasattr(reloaded, "is_global")

    def test_create_ignores_is_global_in_body(self, client, db, auth_headers):
        slug = f"created-{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/v1/admin/cms/widgets",
            json={
                "name": "Analytics",
                "slug": slug,
                "widget_type": "html",
                "is_global": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert "is_global" not in response.get_json()
