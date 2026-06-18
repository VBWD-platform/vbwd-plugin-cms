"""Integration: per-post widgets + content areas on cms_post (real PG, S55).

Mirrors the legacy page-widget enrichment onto the unified post:
  - PUT /admin/cms/posts/<id>/widgets replaces assignments;
  - GET /admin/cms/posts/<id> returns page_assignments + content_blocks;
  - public /cms/posts/<slug> returns content_blocks + access-filtered,
    widget-enriched page_assignments;
  - a per-post widget overrides a layout widget for the same area (the public
    payload carries the post widget);
  - an access-gated widget is hidden for a user lacking the level.

All data is seeded through services/repos (no raw SQL). Restated engineering
requirements: TDD-first; DevOps-first (cold local + CI via the shared ``db``
fixture); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
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


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
        content_block_repo=CmsPostContentBlockRepository(db.session),
    )


def _seed_widget(db, slug, name):
    widget = CmsWidget(
        slug=slug, name=name, widget_type="html", content_json={"html": name}
    )
    db.session.add(widget)
    db.session.commit()
    return widget


def _seed_layout_with_widget(db, area_name, widget_id):
    layout = CmsLayout(
        slug=f"lay-{uuid.uuid4().hex[:8]}",
        name="Lay",
        areas=[{"name": area_name, "type": "page-widget"}],
    )
    db.session.add(layout)
    db.session.commit()
    assignment = CmsLayoutWidget(
        layout_id=layout.id,
        widget_id=widget_id,
        area_name=area_name,
        sort_order=0,
    )
    db.session.add(assignment)
    db.session.commit()
    return layout


def _seed_post(db, slug, layout_id=None, status="published"):
    return _post_service(db).create_post(
        {
            "type": "page",
            "slug": slug,
            "title": f"T {slug}",
            "status": status,
            "content_html": "<p>primary</p>",
            "layout_id": str(layout_id) if layout_id else None,
        }
    )


class TestPostWidgetsRoute:
    def test_put_then_admin_get_returns_page_assignments(
        self, client, db, admin_headers
    ):
        widget = _seed_widget(db, f"w-{uuid.uuid4().hex[:8]}", "Sidebar")
        post = _seed_post(db, f"p-{uuid.uuid4().hex[:8]}")

        put = client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[
                {
                    "widget_id": str(widget.id),
                    "area_name": "sidebar",
                    "sort_order": 0,
                    "required_access_level_ids": [],
                }
            ],
        )
        assert put.status_code == 200
        assert put.get_json()[0]["post_id"] == post["id"]

        got = client.get(f"/api/v1/admin/cms/posts/{post['id']}", headers=admin_headers)
        assert got.status_code == 200
        body = got.get_json()
        assert "content_blocks" in body
        assignments = body["page_assignments"]
        assert len(assignments) == 1
        assert assignments[0]["area_name"] == "sidebar"
        assert assignments[0]["widget"]["id"] == str(widget.id)

    def test_put_then_get_preserves_config_override(self, client, db, admin_headers):
        widget = _seed_widget(db, f"w-{uuid.uuid4().hex[:8]}", "Sidebar")
        post = _seed_post(db, f"p-{uuid.uuid4().hex[:8]}")

        put = client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[
                {
                    "widget_id": str(widget.id),
                    "area_name": "sidebar",
                    "config_override": {"heading": "Just for this page"},
                }
            ],
        )
        assert put.status_code == 200
        assert put.get_json()[0]["config_override"] == {"heading": "Just for this page"}

        got = client.get(f"/api/v1/admin/cms/posts/{post['id']}", headers=admin_headers)
        assignment = got.get_json()["page_assignments"][0]
        assert assignment["config_override"] == {"heading": "Just for this page"}

        # Re-PUT without the override clears it back to None.
        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[{"widget_id": str(widget.id), "area_name": "sidebar"}],
        )
        got = client.get(f"/api/v1/admin/cms/posts/{post['id']}", headers=admin_headers)
        assert got.get_json()["page_assignments"][0]["config_override"] is None

    def test_content_blocks_round_trip(self, client, db, admin_headers):
        post = _seed_post(db, f"p-{uuid.uuid4().hex[:8]}")

        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}",
            headers=admin_headers,
            json={
                "content_blocks": [
                    {
                        "area_name": "sidebar-content",
                        "content_html": "<p>aside</p>",
                        "source_css": ".x{}",
                    }
                ]
            },
        )

        got = client.get(f"/api/v1/admin/cms/posts/{post['id']}", headers=admin_headers)
        blocks = got.get_json()["content_blocks"]
        assert blocks["sidebar-content"]["content_html"] == "<p>aside</p>"
        # Primary SEO body untouched by the block apply.
        assert got.get_json()["content_html"] == "<p>primary</p>"

    def test_public_post_returns_content_blocks_and_assignments(
        self, client, db, admin_headers
    ):
        widget = _seed_widget(db, f"w-{uuid.uuid4().hex[:8]}", "Public")
        slug = f"pub-{uuid.uuid4().hex[:8]}"
        post = _seed_post(db, slug)
        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[{"widget_id": str(widget.id), "area_name": "sidebar"}],
        )
        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}",
            headers=admin_headers,
            json={
                "content_blocks": [
                    {"area_name": "content-below", "content_html": "<p>more</p>"}
                ]
            },
        )

        resp = client.get(f"/api/v1/cms/posts/{slug}?type=page")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["content_blocks"]["content-below"]["content_html"] == "<p>more</p>"
        assert len(body["page_assignments"]) == 1
        assert body["page_assignments"][0]["widget"]["id"] == str(widget.id)

    def test_post_widget_overrides_layout_widget_same_area(
        self, client, db, admin_headers
    ):
        layout_widget = _seed_widget(db, f"lw-{uuid.uuid4().hex[:8]}", "Layout")
        post_widget = _seed_widget(db, f"pw-{uuid.uuid4().hex[:8]}", "PostOverride")
        layout = _seed_layout_with_widget(db, "sidebar", layout_widget.id)
        slug = f"ovr-{uuid.uuid4().hex[:8]}"
        post = _seed_post(db, slug, layout_id=layout.id)
        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[{"widget_id": str(post_widget.id), "area_name": "sidebar"}],
        )

        resp = client.get(f"/api/v1/cms/posts/{slug}?type=page")
        body = resp.get_json()
        # The post-level assignment is what the renderer prefers for the area.
        sidebar = [a for a in body["page_assignments"] if a["area_name"] == "sidebar"]
        assert len(sidebar) == 1
        assert sidebar[0]["widget_id"] == str(post_widget.id)

    def test_access_gated_widget_hidden_for_anonymous(self, client, db, admin_headers):
        widget = _seed_widget(db, f"g-{uuid.uuid4().hex[:8]}", "Gated")
        slug = f"gate-{uuid.uuid4().hex[:8]}"
        post = _seed_post(db, slug)
        gated_level_id = str(uuid.uuid4())
        client.put(
            f"/api/v1/admin/cms/posts/{post['id']}/widgets",
            headers=admin_headers,
            json=[
                {
                    "widget_id": str(widget.id),
                    "area_name": "sidebar",
                    "required_access_level_ids": [gated_level_id],
                }
            ],
        )

        resp = client.get(f"/api/v1/cms/posts/{slug}?type=page")
        body = resp.get_json()
        # Anonymous visitor lacks the gated level -> assignment filtered out.
        assert body["page_assignments"] == []
