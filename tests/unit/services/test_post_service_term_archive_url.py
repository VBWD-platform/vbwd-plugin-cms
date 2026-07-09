"""Unit: PostService surfaces term archive URLs on public reads.

Inc 1 of the CMS term-archives feature needs the fe to render REAL archive links
without re-hardcoding the ``category/``/``tag/`` prefix. So:

* the DETAIL payload (``resolve_published_path`` → ``_with_terms``) tags each
  linked term with its ``archive_url``;
* the LIST payload (``list_posts_by_term`` → ``_serialize_page``) adds a
  ``primary_category`` ``{slug, name, archive_url}`` (or ``None``) per item.

Engineering requirements (binding, restated): TDD-first (this RED set); DI
(repos injected); DRY (one ``term_archive_path`` map); Liskov (no primary → a
clean ``None``, never a raise); no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_term import CmsTerm
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


def _term(term_type, slug, name):
    term = CmsTerm()
    term.id = uuid4()
    term.term_type = term_type
    term.slug = slug
    term.name = name
    term.sort_order = 0
    term.created_at = term.updated_at = datetime.datetime.utcnow()
    return term


def _post(slug="hello", primary_term_id=None):
    post = CmsPost()
    post.id = uuid4()
    post.type = "post"
    post.slug = slug
    post.title = "Hello"
    post.status = "published"
    post.parent_id = None
    post.primary_term_id = primary_term_id
    post.published_at = datetime.datetime.utcnow()
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _service(post, terms_by_id, linked_term_ids):
    repo = MagicMock()
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: (
        post if post.type == ptype and post.slug == slug else None
    )
    term_repo = MagicMock()
    term_repo.find_by_id.side_effect = lambda tid: terms_by_id.get(str(tid))
    post_term_repo = MagicMock()
    post_term_repo.find_by_post.return_value = [
        MagicMock(term_id=tid) for tid in linked_term_ids
    ]
    layout_repo = MagicMock()
    layout_repo.find_default.return_value = None
    layout_widget_repo = MagicMock()
    layout_widget_repo.find_by_layout.return_value = [object()]
    return PostService(
        repo=repo,
        term_repo=term_repo,
        post_term_repo=post_term_repo,
        event_dispatcher=MagicMock(),
        layout_repo=layout_repo,
        style_repo=MagicMock(),
        layout_widget_repo=layout_widget_repo,
    )


class TestDetailPayloadTermArchiveUrl:
    def test_each_linked_term_carries_its_archive_url(self):
        category = _term("category", "gadgets", "Gadgets")
        tag = _term("tag", "vue", "Vue")
        post = _post(slug="hello")
        service = _service(
            post,
            {str(category.id): category, str(tag.id): tag},
            [category.id, tag.id],
        )

        dto = service.resolve_published_path("post", "hello")

        urls = {term["slug"]: term["archive_url"] for term in dto["terms"]}
        assert urls["gadgets"] == "category/gadgets"
        assert urls["vue"] == "tag/vue"


class TestListPayloadPrimaryCategory:
    def test_primary_category_is_surfaced_with_archive_url(self):
        category = _term("category", "gadgets", "Gadgets")
        post = _post(slug="hello", primary_term_id=category.id)
        service = _service(post, {str(category.id): category}, [category.id])
        service._repo.find_by_term_slug.return_value = {
            "items": [post],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }

        result = service.list_posts_by_term("category", "gadgets", post_type="post")

        primary = result["items"][0]["primary_category"]
        assert primary == {
            "slug": "gadgets",
            "name": "Gadgets",
            "archive_url": "category/gadgets",
        }

    def test_primary_category_is_none_when_unset(self):
        post = _post(slug="hello", primary_term_id=None)
        service = _service(post, {}, [])
        service._repo.find_by_term_slug.return_value = {
            "items": [post],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }

        result = service.list_posts_by_term("category", "gadgets", post_type="post")

        assert result["items"][0]["primary_category"] is None


class TestResolveTagTerm:
    """Tags live in the core tag index (NOT cms_term); PostService.resolve_tag_term
    proxies validity through the same tag index the archive listing uses."""

    def test_returns_a_synthetic_term_when_a_published_post_carries_the_tag(self):
        service = _service(_post(), {}, [])
        service._repo.find_by_tag_slug.return_value = {
            "items": [object()],
            "total": 1,
            "page": 1,
            "per_page": 1,
            "pages": 1,
        }

        term = service.resolve_tag_term("new-release")

        assert term == {
            "term_type": "tag",
            "slug": "new-release",
            "name": "New Release",
            "description": None,
            "parent_id": None,
        }
        # Validity is checked against PUBLISHED content only, via the tag index.
        _, kwargs = service._repo.find_by_tag_slug.call_args
        assert kwargs["tag_slug"] == "new-release"
        assert kwargs["status"] == "published"

    def test_returns_none_when_no_published_post_carries_the_tag(self):
        service = _service(_post(), {}, [])
        service._repo.find_by_tag_slug.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "per_page": 1,
            "pages": 1,
        }

        assert service.resolve_tag_term("ghost") is None
