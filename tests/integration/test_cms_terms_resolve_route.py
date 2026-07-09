"""Integration: GET /api/v1/cms/terms/<term_type>/<path:slug> (term resolution).

Inc 1 of the CMS term-archives feature: the fe catch-all resolves a term archive
(``/category/<slug>`` / ``/tag/<slug>``) through this endpoint ONLY after both a
page and a post 404 (precedence page → post → term). The endpoint returns the
term (slug, name, term_type, description, parent_id) plus its ``archive_url``, or
404 for an unknown slug. Categories resolve from ``cms_term``; tags — which live
in the core ``vbwd_entity_tag`` index (D7), NOT ``cms_term`` — resolve to a
SYNTHETIC term, valid iff ≥1 PUBLISHED post carries the tag.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PG via the ``db`` fixture, cold local + CI); SOLID/DI/DRY
(categories via TermService.find_by_slug, tags via the same tag index the
listing uses; the single term_archive_path map — no new query path); Liskov
(absence is a clean 404); clean code; no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services.term_type_registry import TermType
from plugins.cms.src.services.term_service import TermService


@pytest.fixture(autouse=True)
def _term_type_registry_baseline():
    """Deterministic term-type registry: ``category`` + ``tag`` registered.

    The registry is process-global and sibling suites mutate it (clear/register),
    so this suite sets its own baseline (mirroring the plugin's on_enable) instead
    of relying on collection order, then restores it on teardown.
    """
    snapshot = list(term_type_registry.list_term_types())
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
    )
    yield
    term_type_registry.clear_term_types()
    for term_type in snapshot:
        term_type_registry.register_term_type(term_type)


def _make_term(db, term_type, name, slug, description=None):
    term_service = TermService(TermRepository(db.session))
    return term_service.create_term(
        {
            "term_type": term_type,
            "name": name,
            "slug": slug,
            "description": description,
        }
    )


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


def _tag_post(app, post, tag_slug):
    """Attach a CORE tag (``vbwd_entity_tag``) to a cms_post — NOT a cms_term."""
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags("cms_post", post.id, [tag_slug])


def test_resolves_a_category_term_with_archive_url(app, db, client):
    suffix = uuid.uuid4().hex[:8]
    slug = f"gadgets-{suffix}"
    _make_term(db, "category", "Gadgets", slug, description="Shiny things")

    response = client.get(f"/api/v1/cms/terms/category/{slug}")
    body = response.get_json()

    assert response.status_code == 200
    assert body["term_type"] == "category"
    assert body["slug"] == slug
    assert body["name"] == "Gadgets"
    assert body["description"] == "Shiny things"
    assert body["archive_url"] == f"category/{slug}"


def test_resolves_a_tag_from_the_core_index_as_a_synthetic_term(app, db, client):
    # Tags live in the core vbwd_entity_tag index — NOT cms_term. A tag carried by
    # a PUBLISHED post resolves to a synthetic term (name = humanized slug).
    suffix = uuid.uuid4().hex[:8]
    slug = f"new-release-{suffix}"
    post = _make_published_post(db, f"story-{suffix}")
    _tag_post(app, post, slug)

    response = client.get(f"/api/v1/cms/terms/tag/{slug}")
    body = response.get_json()

    assert response.status_code == 200
    assert body["term_type"] == "tag"
    assert body["slug"] == slug
    assert body["description"] is None
    assert body["parent_id"] is None
    # Humanized: `new-release-<suffix>` → `New Release <Suffix>`.
    assert body["name"].startswith("New Release")
    assert body["archive_url"] == f"tag/{slug}"


def test_tag_with_no_published_post_returns_404(app, db, client):
    # A tag only on a DRAFT (or on nothing) is not "valid" → 404, so an unknown
    # tag still falls through to the fe not-found handling.
    suffix = uuid.uuid4().hex[:8]
    slug = f"ghost-tag-{suffix}"
    draft = _make_published_post(db, f"draft-{suffix}")
    draft.status = "draft"
    db.session.commit()
    _tag_post(app, draft, slug)

    response = client.get(f"/api/v1/cms/terms/tag/{slug}")

    assert response.status_code == 404


def test_unknown_tag_slug_returns_404(app, db, client):
    response = client.get("/api/v1/cms/terms/tag/does-not-exist-anywhere")

    assert response.status_code == 404
    assert "error" in response.get_json()


def test_unknown_category_slug_returns_404(app, db, client):
    response = client.get("/api/v1/cms/terms/category/does-not-exist")

    assert response.status_code == 404
    assert "error" in response.get_json()


def test_wrong_term_type_for_existing_category_slug_returns_404(app, db, client):
    suffix = uuid.uuid4().hex[:8]
    slug = f"news-{suffix}"
    _make_term(db, "category", "News", slug)

    # The same slug under the WRONG term type must not resolve: as a tag it is
    # validated against the core tag index (no post carries it) → a clean 404.
    response = client.get(f"/api/v1/cms/terms/tag/{slug}")

    assert response.status_code == 404
