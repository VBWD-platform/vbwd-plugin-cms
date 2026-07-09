"""Integration (real PG): public ``GET /api/v1/cms/widgets/by-slug/<slug>``.

The new "super header" CMS widget fetches another widget (its ``menu`` nav) by
slug at render time, so cms exposes an unauthenticated widget-by-slug read. The
existing public layout routes already embed full widget DTOs, so this surfaces
no new class of data. This suite pins the contract:

  * an ACTIVE widget resolves to 200 + its DTO (menu tree included for a menu
    widget);
  * an unknown slug is 404;
  * an existing-but-INACTIVE widget is 404 (never served publicly);
  * the endpoint needs no auth header.

Data is seeded through the repository (no raw SQL); the shared ``db`` fixture
creates + drops the test DB, so the suite runs cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY; Liskov (missing/inactive → 404 fallback); clean code;
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


def _save_widget(db, *, slug, widget_type="html", is_active=True):
    widget = CmsWidget(
        slug=slug,
        name=slug,
        widget_type=widget_type,
        content_json={"content": ""},
        is_active=is_active,
    )
    CmsWidgetRepository(db.session).save(widget)
    return widget


def _url(slug):
    return f"/api/v1/cms/widgets/by-slug/{slug}"


def test_active_widget_by_slug_returns_200_and_dto(client, db):
    slug = f"nav-{uuid.uuid4().hex[:8]}"
    _save_widget(db, slug=slug, widget_type="menu")

    response = client.get(_url(slug))

    assert response.status_code == 200
    body = response.get_json()
    assert body["slug"] == slug
    # menu widget carries its (empty) tree, proving include_menu is on.
    assert body["menu_items"] == []


def test_unknown_slug_returns_404(client, db):
    response = client.get(_url(f"missing-{uuid.uuid4().hex[:8]}"))
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_inactive_widget_by_slug_returns_404(client, db):
    slug = f"hidden-{uuid.uuid4().hex[:8]}"
    _save_widget(db, slug=slug, is_active=False)

    response = client.get(_url(slug))

    assert response.status_code == 404


def test_endpoint_needs_no_auth(client, db):
    slug = f"pub-{uuid.uuid4().hex[:8]}"
    _save_widget(db, slug=slug)

    # No Authorization header at all — a public read.
    response = client.get(_url(slug))

    assert response.status_code == 200
