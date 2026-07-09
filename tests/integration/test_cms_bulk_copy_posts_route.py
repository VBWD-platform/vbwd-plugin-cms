"""Integration: POST /admin/cms/posts/bulk/copy (real PG).

"Make a copy" for CMS posts (covers both ``type='page'`` and ``type='post'``):
each selected post is duplicated into a fresh DRAFT row (never live) with a
collision-safe slug scoped to its ``type``, a new preview token, no publish
date, not pinned, and not a translation. Owned children — content blocks,
per-post widget placements, and post↔term junction rows — are duplicated and
re-pointed at the new post, keeping ``widget_id`` / ``term_id`` on the SAME
shared widget / term. Seeded through the services/repositories (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_term import CmsTerm, CATEGORY_TERM_TYPE
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.cms_post_widget_repository import (
    CmsPostWidgetRepository,
)
from plugins.cms.src.repositories.cms_post_content_block_repository import (
    CmsPostContentBlockRepository,
)
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType


@pytest.fixture(autouse=True)
def _registry():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()


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


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
    )


def _seed_post(db, post_type="post", slug=None, status="published"):
    slug = slug or f"src-{uuid.uuid4().hex[:8]}"
    return _post_service(db).create_post(
        {
            "type": post_type,
            "slug": slug,
            "title": "My Article",
            "status": status,
            "content_html": "<p>body</p>",
            "pinned": True,
        }
    )


def _seed_term(db):
    slug = f"cat-{uuid.uuid4().hex[:8]}"
    return TermRepository(db.session).save(
        CmsTerm(term_type=CATEGORY_TERM_TYPE, slug=slug, name="Cat")
    )


def _seed_widget(db):
    slug = f"pw-{uuid.uuid4().hex[:8]}"
    return CmsWidgetRepository(db.session).save(
        CmsWidget(slug=slug, name="W", widget_type="html")
    )


class TestBulkCopyPostsRoute:
    def test_copy_creates_fresh_draft_row(self, client, db, admin_headers):
        source = _seed_post(db, status="published")
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [source["id"]]},
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["count"] == 1
        created = body["items"][0]
        assert created["id"] != source["id"]
        assert created["type"] == "post"
        assert created["title"] == "My Article (Copy)"
        assert created["slug"] == f"{source['slug']}-copy"
        assert created["slug_base"] == f"{source['slug']}-copy"
        assert created["status"] == "draft"
        assert created["published_at"] is None
        assert created["pinned"] is False
        assert created["translation_group_id"] is None
        assert created["content_html"] == "<p>body</p>"
        # A fresh, non-null preview token distinct from the source's.
        assert created["preview_token"]
        assert created["preview_token"] != source["preview_token"]

    def test_copy_covers_pages_too(self, client, db, admin_headers):
        source = _seed_post(db, post_type="page")
        created = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [source["id"]]},
            headers=admin_headers,
        ).get_json()["items"][0]
        assert created["type"] == "page"
        assert created["slug"] == f"{source['slug']}-copy"

    def test_slug_unique_scoped_to_type(self, client, db, admin_headers):
        source = _seed_post(db, post_type="post")
        first = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [source["id"]]},
            headers=admin_headers,
        ).get_json()["items"][0]
        second = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [source["id"]]},
            headers=admin_headers,
        ).get_json()["items"][0]
        assert first["slug"] == f"{source['slug']}-copy"
        assert second["slug"] == f"{source['slug']}-copy-2"

    def test_owned_children_duplicated_and_repointed(self, client, db, admin_headers):
        source = _seed_post(db, post_type="post")
        source_id = source["id"]
        term = _seed_term(db)
        widget = _seed_widget(db)
        # Seed one term link, one content block, one post-widget on the source.
        PostTermRepository(db.session).replace_for_post(source_id, [str(term.id)])
        CmsPostContentBlockRepository(db.session).replace_for_post(
            source_id,
            [{"area_name": "sidebar", "content_html": "<b>side</b>", "sort_order": 1}],
        )
        CmsPostWidgetRepository(db.session).replace_for_post(
            source_id,
            [{"widget_id": str(widget.id), "area_name": "footer", "sort_order": 2}],
        )

        created = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [source_id]},
            headers=admin_headers,
        ).get_json()["items"][0]
        new_id = created["id"]

        # Term junction duplicated, re-pointed, SAME shared term.
        new_links = PostTermRepository(db.session).find_by_post(new_id)
        assert [str(link.term_id) for link in new_links] == [str(term.id)]
        # The shared term itself was not duplicated.
        assert TermRepository(db.session).find_by_id(str(term.id)) is not None

        # Content block duplicated + re-pointed.
        new_blocks = CmsPostContentBlockRepository(db.session).find_by_post(new_id)
        assert len(new_blocks) == 1
        assert new_blocks[0].area_name == "sidebar"
        assert str(new_blocks[0].post_id) == new_id

        # Post-widget placement duplicated, re-pointed, SAME shared widget.
        new_widgets = CmsPostWidgetRepository(db.session).find_by_post(new_id)
        assert len(new_widgets) == 1
        assert str(new_widgets[0].widget_id) == str(widget.id)
        assert str(new_widgets[0].post_id) == new_id

        # Originals untouched.
        assert len(PostTermRepository(db.session).find_by_post(source_id)) == 1
        assert (
            len(CmsPostContentBlockRepository(db.session).find_by_post(source_id)) == 1
        )
        assert len(CmsPostWidgetRepository(db.session).find_by_post(source_id)) == 1

    def test_unknown_id_is_skipped(self, client, db, admin_headers):
        source = _seed_post(db)
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": [str(uuid.uuid4()), source["id"]]},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.get_json()["count"] == 1

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": "nope"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/posts/bulk/copy",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
