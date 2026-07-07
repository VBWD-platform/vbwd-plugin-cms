"""Integration (real PG): the S122 post-permalink engine end-to-end.

Proves the write-side transform lands in ``cms_post.slug`` and that every read
surface then keys off it unchanged:

* a structured-mode post assembles ``blog/<category-path>/<slug>`` into ``slug``;
* the public route ``GET /cms/posts/<full-path>?type=post`` resolves it 200;
* the cms sitemap provider's ``loc`` is the computed full path;
* the SEO prerender writes ``var/seo/<full-path>.html`` (nested dirs);
* a published rename (§5a) writes the new file, removes the old, emits exactly
  one idempotent 301 old→new, and the derived canonical follows the computed
  slug when no override is set.

Data is created through PostService/repositories (no raw SQL), so the suite runs
cold local AND in CI.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (the ONE renderer + the ONE canonical rule); Liskov; clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from vbwd.events.bus import event_bus  # noqa: F401  (ensures bus import side-effects)

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.routing_rule_repository import (
    CmsRoutingRuleRepository,
)
from plugins.cms.src.services import post_type_registry, seo_registry, seo_wiring
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.content_event_publisher import ContentEventPublisher
from plugins.cms.src.services.seo_canonical import derive_canonical_url


STRUCTURED_CONFIG = {
    "posts_permalink_mode": "structured",
    "posts_root": "blog",
    "posts_permalink_include_year": False,
    "posts_permalink_uncategorized_slug": "uncategorized",
    "public_base_url": "https://example.test",
}


@pytest.fixture
def seo_var_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _prerender_enabled(monkeypatch):
    monkeypatch.setattr(seo_wiring, "_seo_prerender_enabled", lambda: True)


@pytest.fixture(autouse=True)
def _post_types():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()


def _service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=ContentEventPublisher(),
        routing_rule_repo=CmsRoutingRuleRepository(db.session),
        permalink_config=dict(STRUCTURED_CONFIG),
    )


def _nested_category(db, suffix):
    term_repo = TermRepository(db.session)
    parent = CmsTerm()
    parent.term_type = "category"
    parent.slug = f"electronics-{suffix}"
    parent.name = "Electronics"
    term_repo.save(parent)
    child = CmsTerm()
    child.term_type = "category"
    child.slug = f"phones-{suffix}"
    child.name = "Phones"
    child.parent_id = parent.id
    term_repo.save(child)
    return parent, child


def _seo_file(var_dir, slug):
    return var_dir / "seo" / f"{slug}.html"


def test_structured_post_resolves_and_prerenders(client, db, seo_var_dir):
    seo_wiring.register_seo_pipeline()
    suffix = uuid.uuid4().hex[:8]
    parent, child = _nested_category(db, suffix)

    created = _service(db).create_post(
        {
            "type": "post",
            "title": "My Post",
            "slug": f"my-post-{suffix}",
            "content_html": "<p>Body</p>",
            "status": POST_STATUS_PUBLISHED,
            "term_ids": [str(parent.id), str(child.id)],
            "primary_term_id": str(child.id),
        }
    )
    expected = f"blog/electronics-{suffix}/phones-{suffix}/my-post-{suffix}"
    assert created["slug"] == expected
    assert created["slug_base"] == f"my-post-{suffix}"
    assert created["primary_term_id"] == str(child.id)

    # Public route resolves the full nested path (unchanged read side).
    resp = client.get(f"/api/v1/cms/posts/{expected}?type=post")
    assert resp.status_code == 200
    assert resp.get_json()["slug"] == expected

    # Prerender file written at the nested path.
    assert _seo_file(seo_var_dir, expected).exists()

    # Sitemap loc keys off the computed full path.
    locs = {entry.loc for entry in seo_registry.aggregate_sitemap_entries()}
    assert any(loc.endswith(expected) for loc in locs)


def test_published_rename_moves_url_and_emits_single_301(client, db, seo_var_dir):
    seo_wiring.register_seo_pipeline()
    suffix = uuid.uuid4().hex[:8]
    parent, child = _nested_category(db, suffix)
    service = _service(db)

    created = service.create_post(
        {
            "type": "post",
            "title": "Old Post",
            "slug": f"old-{suffix}",
            "content_html": "<p>Body</p>",
            "status": POST_STATUS_PUBLISHED,
            "term_ids": [str(parent.id), str(child.id)],
            "primary_term_id": str(child.id),
        }
    )
    old_slug = created["slug"]
    old_path = f"blog/electronics-{suffix}/phones-{suffix}/old-{suffix}"
    assert old_slug == old_path
    assert _seo_file(seo_var_dir, old_path).exists()

    # Persist the term assignment so the rename resolves the same primary.
    service.assign_terms(created["id"], [str(parent.id), str(child.id)])

    updated = service.update_post(created["id"], {"slug": f"new-{suffix}"})
    new_path = f"blog/electronics-{suffix}/phones-{suffix}/new-{suffix}"
    assert updated["slug"] == new_path

    # Old static file removed, new one written — no 200 competing at the old path.
    assert not _seo_file(seo_var_dir, old_path).exists()
    assert _seo_file(seo_var_dir, new_path).exists()

    # Exactly one idempotent 301 old→new.
    rules = [
        r
        for r in CmsRoutingRuleRepository(db.session).find_all()
        if r.match_value == f"/{old_path}"
    ]
    assert len(rules) == 1
    rule = rules[0]
    assert rule.match_type == "path_prefix"
    assert rule.target_slug == f"/{new_path}"
    assert rule.redirect_code == 301
    assert rule.is_rewrite is False

    # Idempotent: a second identical save adds no duplicate rule.
    service.update_post(created["id"], {"slug": f"new-{suffix}"})
    rules_again = [
        r
        for r in CmsRoutingRuleRepository(db.session).find_all()
        if r.match_value == f"/{old_path}"
    ]
    assert len(rules_again) == 1

    # Canonical follows the computed slug when no override is set (the DRY rule).
    assert updated["canonical_url"] is None
    assert (
        derive_canonical_url(
            updated["canonical_url"],
            updated["slug"],
            STRUCTURED_CONFIG["public_base_url"],
        )
        == f"{STRUCTURED_CONFIG['public_base_url']}/{new_path}"
    )
