"""Integration: the live S47.1 SEO pipeline end-to-end (real PG).

Publishing a post through PostService (wired with ContentEventPublisher →
EventBus) writes ``${VAR_DIR}/seo/<slug>.html``; trashing it removes the file;
the cms sitemap provider yields a SitemapEntry for the published post. Proves
the on_enable wiring (bus subscribe + provider register) actually fires.
"""
import uuid

import pytest

from vbwd.events.bus import event_bus

from plugins.cms.src.services import seo_registry
from plugins.cms.src.models.cms_post import (
    POST_STATUS_PUBLISHED,
    POST_STATUS_TRASH,
)
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.content_event_publisher import ContentEventPublisher
from plugins.cms.src.services import seo_wiring
from plugins.cms.src.services.seo_wiring import (
    register_seo_pipeline,
    unregister_seo_pipeline,
)


@pytest.fixture
def seo_var_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _prerender_enabled(monkeypatch):
    # These tests exercise the prerender pipeline, so the SEO toggle must be on
    # regardless of whatever ``seo_prerender_enabled`` value the live dev
    # ``plugins/config.json`` happens to hold (an admin may have switched it
    # off). Force it on so the suite stays hermetic.
    monkeypatch.setattr(seo_wiring, "_seo_prerender_enabled", lambda: True)


@pytest.fixture(autouse=True)
def _registry_and_types():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    seo_registry.clear_sitemap_providers()
    yield
    unregister_seo_pipeline()
    seo_registry.clear_sitemap_providers()
    post_type_registry.clear_post_types()


def _service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=ContentEventPublisher(),
    )


def _seo_file(var_dir, slug):
    return var_dir / "seo" / f"{slug}.html"


def test_publish_writes_then_trash_removes(db, seo_var_dir):
    register_seo_pipeline()
    service = _service(db)
    slug = f"page-{uuid.uuid4().hex[:8]}"

    created = service.create_post(
        {
            "type": "page",
            "title": "Live Pricing",
            "slug": slug,
            "content_html": "<p>Plans</p>",
            "canonical_url": f"https://x/{slug}",
            "status": POST_STATUS_PUBLISHED,
        }
    )

    path = _seo_file(seo_var_dir, slug)
    assert path.exists()
    html = path.read_text()
    assert "<title>Live Pricing</title>" in html
    assert '<div id="app"><p>Plans</p></div>' in html

    service.change_status(created["id"], POST_STATUS_TRASH)
    assert not path.exists()


def test_sitemap_provider_yields_published_post(db, seo_var_dir):
    register_seo_pipeline()
    service = _service(db)
    slug = f"page-{uuid.uuid4().hex[:8]}"
    canonical = f"https://x/{slug}"

    service.create_post(
        {
            "type": "page",
            "title": "Indexed",
            "slug": slug,
            "canonical_url": canonical,
            "status": POST_STATUS_PUBLISHED,
        }
    )

    entries = seo_registry.aggregate_sitemap_entries()
    locs = {entry.loc for entry in entries}
    assert canonical in locs


def test_content_changed_reaches_bus_subscriber(db, seo_var_dir):
    register_seo_pipeline()
    assert event_bus.has_subscribers("content.changed")
