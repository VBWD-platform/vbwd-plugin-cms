"""Unit: PostService resolves the default layout on public reads.

Mirrors PostService._with_resolved_style — a post/page WITHOUT an explicit
layout_id picks up the admin-designated default layout (the cms_layout row
flagged ``is_default``) at render time, so freshly imported (layout-less)
pages render with chrome instead of a bare <article>.

The default is keyed on ``layout_repo.find_default()`` (mirrors the
default-STYLE pattern) — there is no longer a ``default_layout_id`` config
value. Critically, unlike style, the default must NOT leak into the
admin/editor payload: get_post keeps the raw layout_id so "no layout" stays
truthful and bulk-assign/clear is honest.

Engineering requirements (binding, restated): TDD-first; DI (layout_repo
injected, default keyed on find_default); Liskov (missing default → fields
present but source 'none', never a failure); DRY (same shape as the style
resolver); no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
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


def _post(post_type="post", slug="hello", layout_id=None):
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
    post.layout_id = layout_id
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_service(post, default_layout=None):
    repo = MagicMock()
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: (
        post if post.type == ptype and post.slug == slug else None
    )
    repo.find_by_id.side_effect = lambda pid: (
        post if str(pid) == str(post.id) else None
    )
    layout_repo = MagicMock()
    layout_repo.find_default.return_value = default_layout
    return PostService(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=MagicMock(),
        event_dispatcher=MagicMock(),
        layout_repo=layout_repo,
        style_repo=MagicMock(),
    )


def _default_layout(active=True):
    layout = MagicMock()
    layout.id = uuid4()
    layout.is_active = active
    return layout


class TestResolvedLayoutOnPublicRead:
    def test_explicit_layout_wins(self):
        explicit = uuid4()
        default = _default_layout()
        post = _post(slug="x", layout_id=explicit)
        service = _make_service(post, default_layout=default)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] == str(explicit)
        assert dto["resolved_layout_source"] == "explicit"

    def test_no_layout_falls_back_to_active_default(self):
        default = _default_layout()
        post = _post(slug="x", layout_id=None)
        service = _make_service(post, default_layout=default)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] == str(default.id)
        assert dto["resolved_layout_source"] == "default"

    def test_page_without_layout_falls_back_to_active_default(self):
        default = _default_layout()
        post = _post(post_type="page", slug="enterprise", layout_id=None)
        service = _make_service(post, default_layout=default)

        dto = service.resolve_published_path("page", "enterprise")

        assert dto["resolved_layout_id"] == str(default.id)
        assert dto["resolved_layout_source"] == "default"

    def test_inactive_default_yields_none(self):
        default = _default_layout(active=False)
        post = _post(slug="x", layout_id=None)
        service = _make_service(post, default_layout=default)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] is None
        assert dto["resolved_layout_source"] == "none"

    def test_no_default_configured_yields_none(self):
        post = _post(slug="x", layout_id=None)
        service = _make_service(post, default_layout=None)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] is None
        assert dto["resolved_layout_source"] == "none"


class TestDefaultNeverLeaksIntoEditor:
    def test_get_post_keeps_raw_layout_id_and_omits_resolved_default(self):
        default = _default_layout()
        post = _post(slug="x", layout_id=None)
        service = _make_service(post, default_layout=default)

        dto = service.get_post(str(post.id))

        # Editor must see the truthful (empty) layout — never the default.
        assert dto["layout_id"] is None
        assert dto.get("resolved_layout_id") != str(default.id)
