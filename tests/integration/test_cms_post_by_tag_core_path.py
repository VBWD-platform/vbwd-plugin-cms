"""S77 D7 — post-by-tag listing reads the core tag path; categories stay on cms_term.

After folding CMS tags into the core tables, ``GET /cms/posts?term_type=tag&
term_slug=…`` must resolve posts via ``vbwd_entity_tag`` (entity_type
``cms_post``), NOT ``cms_post_term``/``cms_term('tag')`` (which no longer holds
tags). Category filtering (``term_type=category``) is unchanged — still the
``cms_term``/``cms_post_term`` join. The ``tag`` term type is deregistered from
the term-type registry (only ``category`` + plugin types remain).

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG
via the ``db`` fixture, clean cold start); SOLID/DI/DRY (tags via the core port;
one home for the reverse-index lookup); Liskov; clean code; no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services.term_type_registry import TermType


@pytest.fixture(autouse=True)
def _category_only_registry():
    """Deterministic registry: ``category`` registered, ``tag`` NOT (D7).

    The term-type registry is process-global and sibling suites mutate it, so
    this suite sets its own baseline (mirroring the plugin's on_enable) instead
    of relying on collection order, then restores it on teardown.
    """
    snapshot = list(term_type_registry.list_term_types())
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    yield
    term_type_registry.clear_term_types()
    for term_type in snapshot:
        term_type_registry.register_term_type(term_type)


def _make_published_post(db, slug):
    from plugins.cms.src.models.cms_post import CmsPost

    post = CmsPost()
    post.type = "post"
    post.slug = slug
    post.title = slug
    post.content_json = {}
    post.status = "published"
    db.session.add(post)
    db.session.commit()
    return post


def test_tag_term_type_deregistered(app):
    assert not term_type_registry.is_registered("tag")
    assert term_type_registry.is_registered("category")


def test_posts_filtered_by_tag_via_core_entity_tag(app, db, client):
    suffix = uuid.uuid4().hex[:8]
    tagged = _make_published_post(db, f"tagged-{suffix}")
    untagged = _make_published_post(db, f"untagged-{suffix}")
    slug = f"howto-{suffix}"

    with app.app_context():
        app.container.tags_and_custom_fields().set_tags("cms_post", tagged.id, [slug])

    body = client.get(f"/api/v1/cms/posts?term_type=tag&term_slug={slug}").get_json()

    returned_slugs = {item["slug"] for item in body["items"]}
    assert tagged.slug in returned_slugs
    assert untagged.slug not in returned_slugs
    assert body["total"] == 1


def test_category_filtering_still_uses_cms_term(app, db, client):
    """Category filtering is unchanged — the cms_term/cms_post_term join."""
    from plugins.cms.src.repositories.post_term_repository import PostTermRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.services.term_service import TermService

    suffix = uuid.uuid4().hex[:8]
    post = _make_published_post(db, f"cat-post-{suffix}")
    term_service = TermService(TermRepository(db.session))
    category = term_service.create_term(
        {"term_type": "category", "name": "Guides", "slug": f"guides-{suffix}"}
    )
    PostTermRepository(db.session).replace_for_post(str(post.id), [category["id"]])

    body = client.get(
        f"/api/v1/cms/posts?term_type=category&term_slug=guides-{suffix}"
    ).get_json()

    assert {item["slug"] for item in body["items"]} == {post.slug}
