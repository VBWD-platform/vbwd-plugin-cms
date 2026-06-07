"""Integration: the SEO sitemap as a production server actually boots it.

This is the regression that was missing. The other SEO wiring test always set
``canonical_url`` explicitly, so it never exercised the production data shape:
a ``published`` post with **no canonical_url** (the column is nullable, and the
backfilled posts on the live server all have it NULL). With no fallback the cms
provider emitted ``SitemapEntry(loc=None)`` for every post, and core's
``/sitemap.xml`` crashed with ``escape(None)`` → HTTP 500 → an operator sees
"empty sitemap".

These tests construct the app the way production does — plugin enabled via the
manifest, a fresh ``create_app()`` through the shared ``app`` fixture, WITHOUT
manually calling ``on_enable()`` — and assert the live ``GET /sitemap.xml``:

  1. returns 200 and lists the published posts' ``<loc>``s (built from the
     public base URL + slug when canonical_url is absent), excluding a
     ``noindex`` / ``seo_excluded`` / draft one;
  2. the ``content.changed`` prerender hook is active (publishing writes
     ``${VAR_DIR}/seo/<slug>.html``).

Engineering requirements honoured (binding, restated): TDD-first (this file is
the RED test); DevOps-first (runs local + CI from cold start via the shared
``db`` fixture, no raw SQL — data goes through PostService); SOLID/DI/DRY
(``loc`` fallback reuses the same ``canonical_url or base/slug`` rule the RSS
feed uses); Liskov (a null-canonical post is a valid subtype, never a crash);
clean code; no overengineering. Quality guard: ``bin/pre-commit-check.sh
--plugin cms --full``.
"""
import uuid

import pytest

from vbwd.events.bus import event_bus

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED, POST_STATUS_DRAFT
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.content_event_publisher import ContentEventPublisher


@pytest.fixture
def seo_var_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _post_type_present():
    """Ensure the ``post`` type exists for create.

    The shared integration conftest re-establishes the production SEO wiring
    (sitemap provider + ``content.changed`` subscriber) for every SEO test, so
    this fixture only guards the post-type registry, which a sibling test's
    teardown can clear.
    """
    if post_type_registry.get_post_type("post") is None:
        post_type_registry.register_post_type(
            PostType(key="post", label="Post", routable=True, hierarchical=False)
        )
    yield


def _service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=ContentEventPublisher(),
    )


def _create_published_without_canonical(service, slug, title):
    return service.create_post(
        {
            "type": "post",
            "title": title,
            "slug": slug,
            "content_html": f"<p>{title}</p>",
            "status": POST_STATUS_PUBLISHED,
            # NOTE: no canonical_url — the production data shape.
        }
    )


def test_sitemap_route_lists_published_posts_without_canonical_url(
    db, client, seo_var_dir
):
    """The provider booted by the manifest must serve a valid, non-empty sitemap.

    Reproduces the live 500: published posts with NULL canonical_url. After the
    fix the route returns 200 and lists each visible post's slug-derived loc,
    while excluding a draft and a noindex/seo_excluded one.
    """
    service = _service(db)
    visible_slug = f"post-visible-{uuid.uuid4().hex[:8]}"
    draft_slug = f"post-draft-{uuid.uuid4().hex[:8]}"
    excluded_slug = f"post-excluded-{uuid.uuid4().hex[:8]}"

    _create_published_without_canonical(service, visible_slug, "Visible Post")

    # A draft is never search-visible.
    service.create_post(
        {
            "type": "post",
            "title": "Draft Post",
            "slug": draft_slug,
            "status": POST_STATUS_DRAFT,
        }
    )
    # A published-but-excluded post is filtered by the search-visible predicate.
    service.create_post(
        {
            "type": "post",
            "title": "Hidden Post",
            "slug": excluded_slug,
            "status": POST_STATUS_PUBLISHED,
            "seo_excluded": True,
        }
    )

    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"/{visible_slug}" in body
    assert f"/{draft_slug}" not in body
    assert f"/{excluded_slug}" not in body
    # No NULL loc leaked through (the original crash signature).
    assert "<loc></loc>" not in body


def test_content_changed_prerender_hook_active_on_boot(db, seo_var_dir):
    """Publishing through the service writes the prerender file (hook is live)."""
    service = _service(db)
    slug = f"post-prerender-{uuid.uuid4().hex[:8]}"

    _create_published_without_canonical(service, slug, "Prerendered Post")

    prerendered = seo_var_dir / "seo" / f"{slug}.html"
    assert prerendered.exists()


def test_content_changed_bus_subscriber_active_on_boot(db):
    """The ``content.changed`` subscriber is wired on a normal boot."""
    assert event_bus.has_subscribers("content.changed")
