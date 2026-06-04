"""Unit: PostService resolves the default style on public reads.

Mirrors CmsPageService._with_resolved_style — since the S47 cutover routes
both pages and posts through PostService, a post/page WITHOUT an explicit
style_id must still pick up the admin-designated default style so the public
renderer can apply it.

Engineering requirements (binding, restated): TDD-first; DI (style_repo
injected); Liskov (absent repo → fields present but null, never a failure);
DRY (same contract as the page resolver); no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import (
    PostType,
    register_post_type,
    clear_post_types,
)


@pytest.fixture(autouse=True)
def _registry():
    clear_post_types()
    register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    yield
    clear_post_types()


def _post(post_type="post", slug="hello", style_id=None):
    post = CmsPost()
    post.id = uuid4()
    post.type = post_type
    post.slug = slug
    post.title = "Hello"
    post.status = "published"
    post.parent_id = None
    post.published_at = datetime.datetime.utcnow()
    post.language = "en"
    post.sort_order = 0
    post.style_id = style_id
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_service(post, default_style=None):
    repo = MagicMock()
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: (
        post if post.type == ptype and post.slug == slug else None
    )
    repo.find_by_id.side_effect = lambda pid: (
        post if str(pid) == str(post.id) else None
    )
    style_repo = MagicMock()
    style_repo.find_default.return_value = default_style
    return PostService(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=MagicMock(),
        event_dispatcher=MagicMock(),
        layout_repo=MagicMock(),
        style_repo=style_repo,
    )


def _default_style(active=True):
    style = MagicMock()
    style.id = uuid4()
    style.is_active = active
    return style


class TestResolvedStyleOnPublicRead:
    def test_post_without_style_falls_back_to_active_default(self):
        default = _default_style()
        post = _post(post_type="post", slug="test23", style_id=None)
        service = _make_service(post, default_style=default)

        dto = service.resolve_published_path("post", "test23")

        assert dto["resolved_style_id"] == str(default.id)
        assert dto["resolved_style_source"] == "default"

    def test_page_without_style_falls_back_to_active_default(self):
        default = _default_style()
        post = _post(post_type="page", slug="enterprise", style_id=None)
        service = _make_service(post, default_style=default)

        dto = service.resolve_published_path("page", "enterprise")

        assert dto["resolved_style_id"] == str(default.id)
        assert dto["resolved_style_source"] == "default"

    def test_explicit_style_wins_over_default(self):
        explicit = uuid4()
        default = _default_style()
        post = _post(slug="x", style_id=explicit)
        service = _make_service(post, default_style=default)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_style_id"] == str(explicit)
        assert dto["resolved_style_source"] == "explicit"

    def test_inactive_default_yields_null(self):
        default = _default_style(active=False)
        post = _post(slug="x", style_id=None)
        service = _make_service(post, default_style=default)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_style_id"] is None
        assert dto["resolved_style_source"] is None

    def test_no_default_configured_yields_null(self):
        post = _post(slug="x", style_id=None)
        service = _make_service(post, default_style=None)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_style_id"] is None
        assert dto["resolved_style_source"] is None

    def test_get_post_also_resolves_for_editor_parity(self):
        default = _default_style()
        post = _post(slug="x", style_id=None)
        service = _make_service(post, default_style=default)

        dto = service.get_post(str(post.id))

        assert dto["resolved_style_id"] == str(default.id)
        assert dto["resolved_style_source"] == "default"
