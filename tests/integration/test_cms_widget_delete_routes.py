"""Integration: widget deletion never 500s (S68 Bug B), real PG.

Two tables reference ``cms_widget.id`` with ``ondelete=RESTRICT``
(``cms_layout_widget``, ``cms_post_widget``; the legacy ``cms_page_widget`` was
retired in S105). The old delete path guarded only layout assignments, so
post-assigned widgets hit the RESTRICT FK → uncaught IntegrityError → 500 +
poisoned session; bulk delete had no guard at all. These tests pin the fixed
contract:

* unused widget → 200;
* in-use widget without ``force`` → 409 with per-kind usage counts (layout AND
  post cases), session usable afterwards;
* ``?force=true`` detaches (join rows deleted) then deletes — the layout / post
  survive, ``cms_menu_item`` rows cascade away;
* bulk delete applies the same guard/force per id and reports per-id results.

Data is seeded through services / repositories (no raw SQL); the shared ``db``
fixture creates + drops the test DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY (guard logic lives once in the service/repo);
Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.models.cms_menu_item import CmsMenuItem
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_post_widget import CmsPostWidget
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_menu_item_repository import (
    CmsMenuItemRepository,
)
from plugins.cms.src.repositories.cms_post_widget_repository import (
    CmsPostWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


@pytest.fixture(autouse=True)
def admin_token(client, db):
    """Log in as admin and return JWT token."""
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


def _create_widget(db, widget_type="html"):
    slug = f"wdel-{uuid.uuid4().hex[:8]}"
    CmsWidgetRepository(db.session).save(
        CmsWidget(slug=slug, name="Delete Me", widget_type=widget_type)
    )
    return CmsWidgetRepository(db.session).find_by_slug(slug)


def _assign_to_layout(db, widget_id):
    slug = f"lay-{uuid.uuid4().hex[:8]}"
    layout = CmsLayoutRepository(db.session).save(
        CmsLayout(slug=slug, name="Layout", areas=[{"name": "header"}])
    )
    CmsLayoutWidgetRepository(db.session).replace_for_layout(
        str(layout.id),
        [{"widget_id": str(widget_id), "area_name": "header", "sort_order": 0}],
    )
    return layout


def _assign_to_post(db, widget_id):
    post = CmsPost(type="page", slug=f"post-{uuid.uuid4().hex[:8]}", title="Post")
    db.session.add(post)
    db.session.commit()
    CmsPostWidgetRepository(db.session).replace_for_post(
        str(post.id),
        [{"widget_id": str(widget_id), "area_name": "header", "sort_order": 0}],
    )
    return post


def _count(db, model_class, **filters):
    return db.session.query(model_class).filter_by(**filters).count()


class TestSingleDelete:
    def test_delete_unused_widget_succeeds(self, client, db, auth_headers):
        widget = _create_widget(db)
        response = client.delete(
            f"/api/v1/admin/cms/widgets/{widget.id}", headers=auth_headers
        )
        assert response.status_code == 200, response.get_json()
        assert CmsWidgetRepository(db.session).find_by_id(str(widget.id)) is None

    def test_delete_layout_assigned_widget_returns_409_with_usage(
        self, client, db, auth_headers
    ):
        widget = _create_widget(db)
        _assign_to_layout(db, widget.id)
        response = client.delete(
            f"/api/v1/admin/cms/widgets/{widget.id}", headers=auth_headers
        )
        assert response.status_code == 409
        body = response.get_json()
        assert body["usage"]["layouts"] == 1
        # The session must remain usable (not poisoned by a failed flush).
        follow_up = client.get(
            f"/api/v1/admin/cms/widgets/{widget.id}", headers=auth_headers
        )
        assert follow_up.status_code == 200

    def test_delete_post_assigned_widget_returns_409_not_500(
        self, client, db, auth_headers
    ):
        """Regression: only layout assignments were guarded — a post-assigned
        widget passed the guard and the RESTRICT FK turned into a 500."""
        widget = _create_widget(db)
        _assign_to_post(db, widget.id)
        response = client.delete(
            f"/api/v1/admin/cms/widgets/{widget.id}", headers=auth_headers
        )
        assert response.status_code == 409, response.get_json()
        assert response.get_json()["usage"]["posts"] == 1
        follow_up = client.get(
            f"/api/v1/admin/cms/widgets/{widget.id}", headers=auth_headers
        )
        assert follow_up.status_code == 200

    def test_force_delete_detaches_and_deletes(self, client, db, auth_headers):
        widget = _create_widget(db, widget_type="menu")
        CmsMenuItemRepository(db.session).replace_tree(
            str(widget.id), [{"label": "Home", "url": "/", "sort_order": 0}]
        )
        layout = _assign_to_layout(db, widget.id)
        post = _assign_to_post(db, widget.id)
        widget_id = str(widget.id)

        response = client.delete(
            f"/api/v1/admin/cms/widgets/{widget_id}?force=true", headers=auth_headers
        )
        assert response.status_code == 200, response.get_json()

        assert CmsWidgetRepository(db.session).find_by_id(widget_id) is None
        assert _count(db, CmsLayoutWidget, widget_id=widget_id) == 0
        assert _count(db, CmsPostWidget, widget_id=widget_id) == 0
        assert _count(db, CmsMenuItem, widget_id=widget_id) == 0
        # The hosts survive — force only un-places the widget.
        assert _count(db, CmsLayout, id=layout.id) == 1
        assert _count(db, CmsPost, id=post.id) == 1

    def test_delete_missing_widget_returns_404(self, client, db, auth_headers):
        response = client.delete(
            f"/api/v1/admin/cms/widgets/{uuid.uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404


class TestBulkDelete:
    def test_bulk_delete_mixed_used_and_unused_never_500s(
        self, client, db, auth_headers
    ):
        used = _create_widget(db)
        unused = _create_widget(db)
        _assign_to_post(db, used.id)
        used_id, unused_id = str(used.id), str(unused.id)

        response = client.post(
            "/api/v1/admin/cms/widgets/bulk",
            json={"ids": [used_id, unused_id]},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["deleted"] == 1
        by_id = {entry["id"]: entry for entry in body["results"]}
        assert by_id[used_id]["status"] == "blocked"
        assert by_id[used_id]["usage"]["posts"] == 1
        assert by_id[unused_id]["status"] == "deleted"

        repository = CmsWidgetRepository(db.session)
        assert repository.find_by_id(used_id) is not None
        assert repository.find_by_id(unused_id) is None

    def test_bulk_delete_force_deletes_used_widgets(self, client, db, auth_headers):
        used = _create_widget(db)
        _assign_to_layout(db, used.id)
        used_id = str(used.id)

        response = client.post(
            "/api/v1/admin/cms/widgets/bulk",
            json={"ids": [used_id], "force": True},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["deleted"] == 1
        assert CmsWidgetRepository(db.session).find_by_id(used_id) is None
        assert _count(db, CmsLayoutWidget, widget_id=used_id) == 0
