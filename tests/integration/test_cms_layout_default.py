"""Integration tests for the default-layout endpoints.

Mirrors test_cms_style_default.py — walks the HTTP surface the admin UI
uses and exercises the single-default invariant end-to-end against a real
DB session.

Engineering requirements (binding, restated): TDD-first; DevOps-first
(real PG, cold-start safe); SOLID/DI/DRY; Liskov (single-default invariant);
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import pytest
import uuid


@pytest.fixture
def admin_token(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    if resp.status_code != 200:
        pytest.skip("Admin user not available in test DB")
    data = resp.get_json()
    return data.get("token") or data.get("access_token")


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


_AREAS = [
    {"name": "page-header", "type": "header", "label": "Header"},
    {"name": "main-body", "type": "content", "label": "Content"},
    {"name": "page-footer", "type": "footer", "label": "Footer"},
]


def _make_layout(client, auth_headers, slug_prefix="layout"):
    resp = client.post(
        "/api/v1/admin/cms/layouts",
        json={
            "name": f"Test {slug_prefix}",
            "slug": f"{slug_prefix}-{uuid.uuid4().hex[:8]}",
            "areas": _AREAS,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


class TestLayoutDefaultEndpoints:
    def test_post_default_promotes_layout(self, client, db, auth_headers):
        a = _make_layout(client, auth_headers, "a")
        resp = client.post(
            f"/api/v1/admin/cms/layouts/{a['id']}/default",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["is_default"] is True

    def test_post_default_demotes_previous(self, client, db, auth_headers):
        a = _make_layout(client, auth_headers, "a")
        b = _make_layout(client, auth_headers, "b")
        client.post(
            f"/api/v1/admin/cms/layouts/{a['id']}/default", headers=auth_headers
        )
        client.post(
            f"/api/v1/admin/cms/layouts/{b['id']}/default", headers=auth_headers
        )
        a_after = client.get(
            f"/api/v1/admin/cms/layouts/{a['id']}", headers=auth_headers
        ).get_json()
        b_after = client.get(
            f"/api/v1/admin/cms/layouts/{b['id']}", headers=auth_headers
        ).get_json()
        assert a_after["is_default"] is False
        assert b_after["is_default"] is True

    def test_delete_default_clears_flag(self, client, db, auth_headers):
        a = _make_layout(client, auth_headers, "a")
        client.post(
            f"/api/v1/admin/cms/layouts/{a['id']}/default", headers=auth_headers
        )
        resp = client.delete("/api/v1/admin/cms/layouts/default", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()

        a_after = client.get(
            f"/api/v1/admin/cms/layouts/{a['id']}", headers=auth_headers
        ).get_json()
        assert a_after["is_default"] is False

    def test_only_one_layout_default_at_a_time(self, client, db, auth_headers):
        a = _make_layout(client, auth_headers, "a")
        b = _make_layout(client, auth_headers, "b")
        client.post(
            f"/api/v1/admin/cms/layouts/{a['id']}/default", headers=auth_headers
        )
        client.post(
            f"/api/v1/admin/cms/layouts/{b['id']}/default", headers=auth_headers
        )
        resp = client.get(
            "/api/v1/admin/cms/layouts?per_page=100", headers=auth_headers
        )
        items = resp.get_json()["items"]
        defaults = [layout for layout in items if layout["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["id"] == b["id"]

    def test_set_default_requires_admin(self, client, db):
        # No auth header → the admin guard rejects before any service call.
        resp = client.post(f"/api/v1/admin/cms/layouts/{uuid.uuid4()}/default")
        assert resp.status_code in (401, 403)

    def test_clear_default_requires_admin(self, client, db):
        resp = client.delete("/api/v1/admin/cms/layouts/default")
        assert resp.status_code in (401, 403)
