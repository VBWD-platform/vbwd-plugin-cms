"""Integration tests for the default-style endpoints (sprint 26).

Walks the HTTP surface the admin UI will actually use. Exercises the
single-default invariant end-to-end against a real DB session.
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


def _make_style(client, auth_headers, slug_prefix="style"):
    resp = client.post(
        "/api/v1/admin/cms/styles",
        json={
            "name": f"Test {slug_prefix}",
            "slug": f"{slug_prefix}-{uuid.uuid4().hex[:8]}",
            "source_css": f"/* {slug_prefix} */ body {{}}",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


class TestStyleDefaultEndpoints:
    def test_post_default_promotes_style(self, client, db, auth_headers):
        a = _make_style(client, auth_headers, "a")
        resp = client.post(
            f"/api/v1/admin/cms/styles/{a['id']}/default",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["is_default"] is True

    def test_post_default_demotes_previous(self, client, db, auth_headers):
        a = _make_style(client, auth_headers, "a")
        b = _make_style(client, auth_headers, "b")
        client.post(
            f"/api/v1/admin/cms/styles/{a['id']}/default", headers=auth_headers
        )
        client.post(
            f"/api/v1/admin/cms/styles/{b['id']}/default", headers=auth_headers
        )
        a_after = client.get(
            f"/api/v1/admin/cms/styles/{a['id']}", headers=auth_headers
        ).get_json()
        b_after = client.get(
            f"/api/v1/admin/cms/styles/{b['id']}", headers=auth_headers
        ).get_json()
        assert a_after["is_default"] is False
        assert b_after["is_default"] is True

    def test_delete_default_clears_flag(self, client, db, auth_headers):
        a = _make_style(client, auth_headers, "a")
        client.post(
            f"/api/v1/admin/cms/styles/{a['id']}/default", headers=auth_headers
        )
        resp = client.delete(
            "/api/v1/admin/cms/styles/default", headers=auth_headers
        )
        assert resp.status_code == 200, resp.get_json()

        a_after = client.get(
            f"/api/v1/admin/cms/styles/{a['id']}", headers=auth_headers
        ).get_json()
        assert a_after["is_default"] is False

    def test_public_default_css_serves_css(self, client, db, auth_headers):
        a = _make_style(client, auth_headers, "public")
        client.post(
            f"/api/v1/admin/cms/styles/{a['id']}/default", headers=auth_headers
        )
        resp = client.get("/api/v1/cms/styles/default/css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["Content-Type"]
        assert a["slug"] in resp.data.decode() or "body" in resp.data.decode()

    def test_public_default_css_404s_when_none(self, client, db, auth_headers):
        # Ensure no default set
        client.delete("/api/v1/admin/cms/styles/default", headers=auth_headers)
        resp = client.get("/api/v1/cms/styles/default/css")
        assert resp.status_code == 404

    def test_list_exposes_is_default_flag(self, client, db, auth_headers):
        a = _make_style(client, auth_headers, "listed")
        client.post(
            f"/api/v1/admin/cms/styles/{a['id']}/default", headers=auth_headers
        )
        resp = client.get(
            "/api/v1/admin/cms/styles?per_page=100", headers=auth_headers
        )
        items = resp.get_json()["items"]
        defaults = [s for s in items if s["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["id"] == a["id"]
