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

_UNSET = object()


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


def _make_service(post, default_layout=None, layout_widget_repo=_UNSET):
    repo = MagicMock()
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: (
        post if post.type == ptype and post.slug == slug else None
    )
    repo.find_by_id.side_effect = lambda pid: (
        post if str(pid) == str(post.id) else None
    )
    layout_repo = MagicMock()
    layout_repo.find_default.return_value = default_layout
    kwargs = dict(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=MagicMock(),
        event_dispatcher=MagicMock(),
        layout_repo=layout_repo,
        style_repo=MagicMock(),
    )
    # Default: every layout is "seeded" (≥1 placement) so the existing tests
    # keep their explicit/default semantics. A test passing layout_widget_repo
    # exercises the not-seeded fallback; passing None drops the repo entirely.
    if layout_widget_repo is _UNSET:
        seeded_repo = MagicMock()
        seeded_repo.find_by_layout.return_value = [object()]
        kwargs["layout_widget_repo"] = seeded_repo
    elif layout_widget_repo is not None:
        kwargs["layout_widget_repo"] = layout_widget_repo
    return PostService(**kwargs)


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


def _placement_repo(placement_count):
    """A layout-widget repo stub whose find_by_layout returns ``placement_count``
    placement rows (the cms_layout_widget rows = how "seeded" a layout is)."""
    repo = MagicMock()
    repo.find_by_layout.return_value = [object() for _ in range(placement_count)]
    return repo


class TestUnseededExplicitLayoutFallsBackToDefault:
    """NEW: an explicit layout with ZERO widget placements ("not seeded") is
    unusable — fall back to the active default so the page renders chrome +
    body instead of blank."""

    def test_explicit_layout_with_placements_is_used(self):
        explicit = uuid4()
        default = _default_layout()
        post = _post(slug="x", layout_id=explicit)
        service = _make_service(
            post, default_layout=default, layout_widget_repo=_placement_repo(2)
        )

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] == str(explicit)
        assert dto["resolved_layout_source"] == "explicit"

    def test_explicit_unseeded_layout_falls_back_to_active_default(self):
        explicit = uuid4()
        default = _default_layout()
        post = _post(slug="x", layout_id=explicit)
        service = _make_service(
            post, default_layout=default, layout_widget_repo=_placement_repo(0)
        )

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] == str(default.id)
        assert dto["resolved_layout_source"] == "default"

    def test_explicit_unseeded_layout_no_default_yields_none(self):
        explicit = uuid4()
        post = _post(slug="x", layout_id=explicit)
        service = _make_service(
            post, default_layout=None, layout_widget_repo=_placement_repo(0)
        )

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] is None
        assert dto["resolved_layout_source"] == "none"

    def test_no_placement_repo_treats_explicit_as_usable(self):
        explicit = uuid4()
        default = _default_layout()
        post = _post(slug="x", layout_id=explicit)
        service = _make_service(post, default_layout=default, layout_widget_repo=None)

        dto = service.resolve_published_path("post", "x")

        assert dto["resolved_layout_id"] == str(explicit)
        assert dto["resolved_layout_source"] == "explicit"


class TestDefaultNeverLeaksIntoEditor:
    def test_get_post_keeps_raw_layout_id_and_omits_resolved_default(self):
        default = _default_layout()
        post = _post(slug="x", layout_id=None)
        service = _make_service(post, default_layout=default)

        dto = service.get_post(str(post.id))

        # Editor must see the truthful (empty) layout — never the default.
        assert dto["layout_id"] is None
        assert dto.get("resolved_layout_id") != str(default.id)


def _term(term_type, slug, name):
    """A CmsTerm-like mock whose to_dict mirrors the model's full payload."""
    term_id = uuid4()
    term = MagicMock()
    term.id = term_id
    term.term_type = term_type
    term.to_dict.return_value = {
        "id": str(term_id),
        "term_type": term_type,
        "slug": slug,
        "name": name,
        "parent_id": None,
        "description": None,
        "seo_excluded": False,
        "sort_order": 0,
    }
    return term


def _link(term_id):
    link = MagicMock()
    link.term_id = term_id
    return link


def _make_service_with_terms(post, links, terms_by_id, default_layout=None):
    """Wire find_by_post → links and find_by_id → the matching term (or None)."""
    service = _make_service(post, default_layout=default_layout)
    service._post_term_repo.find_by_post.return_value = links
    service._term_repo.find_by_id.side_effect = lambda tid: terms_by_id.get(str(tid))
    return service


class TestResolvedPathCarriesFullTerms:
    """The public single-post resolver must return each linked term's FULL
    dict (category + tag) so the frontend can render a tag cloud."""

    def test_resolve_published_path_includes_full_category_and_tag_terms(self):
        post = _post(slug="x", layout_id=None)
        category = _term("category", "news", "News")
        tag = _term("tag", "python", "Python")
        terms_by_id = {str(category.id): category, str(tag.id): tag}
        links = [_link(category.id), _link(tag.id)]
        service = _make_service_with_terms(post, links, terms_by_id)

        dto = service.resolve_published_path("post", "x")

        assert dto["terms"] == [category.to_dict.return_value, tag.to_dict.return_value]
        term_types = {term["term_type"] for term in dto["terms"]}
        assert term_types == {"category", "tag"}
        # Existing layout/style wrapping must remain intact.
        assert "resolved_layout_source" in dto

    def test_dangling_link_is_skipped(self):
        post = _post(slug="x", layout_id=None)
        category = _term("category", "news", "News")
        terms_by_id = {str(category.id): category}
        missing_term_id = uuid4()
        links = [_link(category.id), _link(missing_term_id)]
        service = _make_service_with_terms(post, links, terms_by_id)

        dto = service.resolve_published_path("post", "x")

        assert dto["terms"] == [category.to_dict.return_value]

    def test_no_links_yields_empty_terms_list(self):
        post = _post(slug="x", layout_id=None)
        service = _make_service_with_terms(post, [], {})

        dto = service.resolve_published_path("post", "x")

        assert dto["terms"] == []
