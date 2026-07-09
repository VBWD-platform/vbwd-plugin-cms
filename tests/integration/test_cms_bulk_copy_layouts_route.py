"""Integration: POST /admin/cms/layouts/bulk/copy (real PG).

"Make a copy" for CMS layouts: each selected layout is duplicated into a fresh,
inactive, non-default row with a collision-safe slug. Owned children
(``cms_layout_widget`` placements) are duplicated and re-pointed at the new
layout, keeping ``widget_id`` on the SAME shared widget. Copying a layout must
NOT copy or modify any page/post that merely references it. Seeded through the
repositories (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.post_repository import PostRepository


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
    slug = f"lw-{uuid.uuid4().hex[:8]}"
    return CmsWidgetRepository(db.session).save(
        CmsWidget(slug=slug, name="W", widget_type="html")
    )


def _seed_layout(db, with_widget=None):
    slug = f"lay-{uuid.uuid4().hex[:8]}"
    layout = CmsLayoutRepository(db.session).save(
        CmsLayout(
            slug=slug,
            name="Home Layout",
            areas=[{"name": "header", "type": "header"}],
            is_active=True,
            is_default=True,
        )
    )
    if with_widget is not None:
        CmsLayoutWidgetRepository(db.session).replace_for_layout(
            str(layout.id),
            [
                {
                    "widget_id": str(with_widget.id),
                    "area_name": "header",
                    "sort_order": 3,
                    "required_access_level_ids": [],
                }
            ],
        )
    return layout


def _seed_post_using_layout(db, layout_id):
    post = CmsPost(
        type="page",
        slug=f"pg-{uuid.uuid4().hex[:8]}",
        title="Page",
        layout_id=layout_id,
        status="published",
    )
    db.session.add(post)
    db.session.commit()
    return post


class TestBulkCopyLayoutsRoute:
    def test_copy_creates_inactive_non_default_row(self, client, db, admin_headers):
        layout = _seed_layout(db)
        resp = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(layout.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["count"] == 1
        created = body["items"][0]
        assert created["id"] != str(layout.id)
        assert created["name"] == "Home Layout (Copy)"
        assert created["slug"] == f"{layout.slug}-copy"
        assert created["is_active"] is False
        assert created["is_default"] is False

    def test_owned_widget_placements_are_duplicated_and_repointed(
        self, client, db, admin_headers
    ):
        widget = _seed_widget(db)
        layout = _seed_layout(db, with_widget=widget)
        created = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(layout.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        lw_repo = CmsLayoutWidgetRepository(db.session)
        new_placements = lw_repo.find_by_layout(created["id"])
        assert len(new_placements) == 1
        placement = new_placements[0]
        # Re-pointed at the new layout ...
        assert str(placement.layout_id) == created["id"]
        # ... but still points at the SAME shared widget (never duplicated).
        assert str(placement.widget_id) == str(widget.id)
        assert placement.area_name == "header"
        assert placement.sort_order == 3
        # Original placements untouched.
        assert len(lw_repo.find_by_layout(str(layout.id))) == 1
        # The shared widget was not duplicated.
        assert CmsWidgetRepository(db.session).find_by_slug(widget.slug) is not None

    def test_copying_layout_does_not_copy_or_repoint_pages(
        self, client, db, admin_headers
    ):
        """Explicit user requirement: copying a layout used by 2 posts leaves the
        post count unchanged and both posts still point at the ORIGINAL layout."""
        layout = _seed_layout(db)
        post_a = _seed_post_using_layout(db, layout.id)
        post_b = _seed_post_using_layout(db, layout.id)
        before = PostRepository(db.session).find_paginated(per_page=1000)["total"]

        created = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(layout.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]

        after = PostRepository(db.session).find_paginated(per_page=1000)["total"]
        assert after == before
        repo = PostRepository(db.session)
        for post in (post_a, post_b):
            reloaded = repo.find_by_id(str(post.id))
            assert str(reloaded.layout_id) == str(layout.id)
            assert str(reloaded.layout_id) != created["id"]

    def test_copy_same_source_twice_is_collision_safe(self, client, db, admin_headers):
        layout = _seed_layout(db)
        first = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(layout.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        second = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(layout.id)]},
            headers=admin_headers,
        ).get_json()["items"][0]
        assert first["slug"] == f"{layout.slug}-copy"
        assert second["slug"] == f"{layout.slug}-copy-2"

    def test_unknown_id_is_skipped(self, client, db, admin_headers):
        layout = _seed_layout(db)
        resp = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": [str(uuid.uuid4()), str(layout.id)]},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 1

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/layouts/bulk/copy",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
