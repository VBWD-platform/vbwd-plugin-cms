"""Integration tests verifying CMS data actually persists across requests.

These tests catch the class of bug where repositories call flush() but not
commit(), causing data to be lost when the session ends.
"""
import pytest
import uuid


@pytest.fixture(autouse=True)
def admin_token(client, db):
    """Log in as admin and return JWT token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "AdminPass123@",
        },
    )
    if resp.status_code != 200:
        pytest.skip("Admin user not available in test DB")
    return resp.get_json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestCmsPagePersistence:
    """Pages must survive across DB sessions (commit, not just flush)."""

    def test_create_then_update_page(self, client, db, auth_headers):
        """POST creates a page; a subsequent PUT on the same ID must succeed.

        This test would fail if save() only calls flush() without commit(),
        because the second request opens a new session and can't see the row.
        """
        # Create
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Persistence Test",
                "slug": f"persistence-{uuid.uuid4().hex[:8]}",
                "language": "en",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.get_json()
        page_id = resp.get_json()["id"]

        # Update (separate request = potentially new session)
        resp = client.put(
            f"/api/v1/admin/cms/pages/{page_id}",
            json={
                "name": "Persistence Test Updated",
            },
            headers=auth_headers,
        )
        assert (
            resp.status_code == 200
        ), f"PUT returned {resp.status_code}: {resp.get_json()}"
        assert resp.get_json()["name"] == "Persistence Test Updated"

    def test_create_then_delete_page(self, client, db, auth_headers):
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Delete Test",
                "slug": f"delete-{uuid.uuid4().hex[:8]}",
                "language": "en",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        page_id = resp.get_json()["id"]

        resp = client.delete(f"/api/v1/admin/cms/pages/{page_id}", headers=auth_headers)
        assert resp.status_code == 204

        # Confirm it's gone
        resp = client.get(f"/api/v1/admin/cms/pages/{page_id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_created_page_appears_in_list(self, client, db, auth_headers):
        slug = f"list-{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "List Test",
                "slug": slug,
                "language": "en",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        resp = client.get("/api/v1/admin/cms/pages", headers=auth_headers)
        assert resp.status_code == 200
        slugs = [p["slug"] for p in resp.get_json()["items"]]
        assert slug in slugs, f"Created page slug '{slug}' not found in list: {slugs}"


class TestCmsCategoryPersistence:
    def test_create_then_update_category(self, client, db, auth_headers):
        resp = client.post(
            "/api/v1/admin/cms/categories",
            json={
                "name": "Test Cat",
                "slug": f"cat-{uuid.uuid4().hex[:8]}",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.get_json()
        cat_id = resp.get_json()["id"]

        resp = client.put(
            f"/api/v1/admin/cms/categories/{cat_id}",
            json={
                "name": "Test Cat Updated",
            },
            headers=auth_headers,
        )
        assert (
            resp.status_code == 200
        ), f"PUT returned {resp.status_code}: {resp.get_json()}"
        assert resp.get_json()["name"] == "Test Cat Updated"

    def test_create_then_delete_category(self, client, db, auth_headers):
        resp = client.post(
            "/api/v1/admin/cms/categories",
            json={
                "name": "Delete Cat",
                "slug": f"del-cat-{uuid.uuid4().hex[:8]}",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        cat_id = resp.get_json()["id"]

        resp = client.delete(
            f"/api/v1/admin/cms/categories/{cat_id}", headers=auth_headers
        )
        assert resp.status_code == 204


class TestCmsMultiSegmentSlug:
    """cms_page slugs may contain forward slashes (multi-segment paths)."""

    def test_create_and_fetch_multi_segment_slug(self, client, db, auth_headers):
        slug = f"blog/2026/{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Multi-Segment Test",
                "slug": slug,
                "language": "en",
                "is_published": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.get_json()

        resp = client.get(f"/api/v1/cms/pages/{slug}")
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["slug"] == slug

    def test_multi_segment_slug_uniqueness(self, client, db, auth_headers):
        slug = f"a/b/{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Unique Slug 1",
                "slug": slug,
                "language": "en",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Unique Slug 2",
                "slug": slug,
                "language": "en",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 409

    def test_deeply_nested_slug(self, client, db, auth_headers):
        slug = f"something/anothersomething/{uuid.uuid4().hex[:8]}/leaf"
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": "Deep Slug",
                "slug": slug,
                "language": "en",
                "is_published": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201

        resp = client.get(f"/api/v1/cms/pages/{slug}")
        assert resp.status_code == 200
        assert resp.get_json()["slug"] == slug


class TestCmsBulkPersistence:
    def _create_page(self, client, auth_headers, name_suffix=""):
        resp = client.post(
            "/api/v1/admin/cms/pages",
            json={
                "name": f"Bulk Page {name_suffix}",
                "slug": f"bulk-{uuid.uuid4().hex[:8]}",
                "language": "en",
                "is_published": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        return resp.get_json()["id"]

    def test_bulk_publish_persists(self, client, db, auth_headers):
        ids = [self._create_page(client, auth_headers, i) for i in range(3)]

        resp = client.post(
            "/api/v1/admin/cms/pages/bulk",
            json={
                "ids": ids,
                "action": "publish",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Verify each page is now published
        for page_id in ids:
            resp = client.get(
                f"/api/v1/admin/cms/pages/{page_id}", headers=auth_headers
            )
            assert resp.status_code == 200
            assert resp.get_json()["is_published"] is True

    def test_bulk_delete_persists(self, client, db, auth_headers):
        ids = [self._create_page(client, auth_headers, i) for i in range(2)]

        resp = client.post(
            "/api/v1/admin/cms/pages/bulk",
            json={
                "ids": ids,
                "action": "delete",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

        for page_id in ids:
            resp = client.get(
                f"/api/v1/admin/cms/pages/{page_id}", headers=auth_headers
            )
            assert resp.status_code == 404
