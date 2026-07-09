"""Unit: PostService attaches per-post ``tags`` on the archive LIST payload.

The fe archive card (``PostCard.vue``) renders tag chips gated by ``show_tags``,
resolving each tag's link from its ``archive_url``. The DETAIL endpoint already
enriches tags (via the core tags port), but the LIST serialization
(``_serialize_page`` behind ``list_posts`` / ``list_posts_by_term``) omitted
them, so archive cards rendered no tags.

This RED set pins the new contract:

* every list item carries a ``tags`` list of ``{slug, name, archive_url}``
  (``archive_url == "tag/<slug>"``), ``[]`` for a post with no tags;
* tags are fetched in ONE bulk call per core entity type (no N+1) — the page's
  ids go through ``get_tags_bulk`` exactly once for ``cms_post``;
* a missing tags port degrades to ``[]`` (the disabled-feature path, Liskov).

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (runs local + CI cold); SOLID/ISP (narrow tags port); DI (port
injected); DRY (one ``term_archive_path``/``humanize_term_slug`` map); Liskov
(no port → clean ``[]``, never a raise); no overengineering. Quality guard:
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


def _post(slug="hello", post_type="post"):
    post = CmsPost()
    post.id = uuid4()
    post.type = post_type
    post.slug = slug
    post.title = "Hello"
    post.status = "published"
    post.parent_id = None
    post.primary_term_id = None
    post.published_at = datetime.datetime.utcnow()
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _service(posts, tags_by_id, tags_port=None):
    repo = MagicMock()
    repo.find_paginated.return_value = {
        "items": posts,
        "total": len(posts),
        "page": 1,
        "per_page": 20,
        "pages": 1,
    }
    term_repo = MagicMock()
    term_repo.find_by_id.return_value = None
    post_term_repo = MagicMock()
    post_term_repo.find_by_post.return_value = []
    if tags_port is None and tags_by_id is not None:
        tags_port = MagicMock()
        tags_port.get_tags_bulk.side_effect = lambda entity_type, entity_ids: {
            entity_id: tags_by_id.get(entity_id, []) for entity_id in entity_ids
        }
    return PostService(
        repo=repo,
        term_repo=term_repo,
        post_term_repo=post_term_repo,
        event_dispatcher=MagicMock(),
        layout_repo=MagicMock(find_default=MagicMock(return_value=None)),
        style_repo=MagicMock(find_default=MagicMock(return_value=None)),
        tags_port=tags_port,
    )


class TestListPayloadTags:
    def test_each_item_carries_tag_chips_with_archive_url(self):
        post = _post()
        service = _service([post], {post.id: ["vue", "new-release"]})

        result = service.list_posts(post_type="post", status="published")

        tags = result["items"][0]["tags"]
        assert tags == [
            {"slug": "vue", "name": "Vue", "archive_url": "tag/vue"},
            {
                "slug": "new-release",
                "name": "New Release",
                "archive_url": "tag/new-release",
            },
        ]

    def test_post_without_tags_gets_empty_list(self):
        post = _post()
        service = _service([post], {})

        result = service.list_posts(post_type="post", status="published")

        assert result["items"][0]["tags"] == []

    def test_tags_are_fetched_in_one_bulk_call_for_the_page(self):
        posts = [_post(slug=f"p{index}") for index in range(5)]
        tags_by_id = {post.id: ["vue"] for post in posts}
        service = _service(posts, tags_by_id)

        service.list_posts(post_type="post", status="published")

        # ONE bulk call for the whole cms_post page — never one per post (no N+1).
        tags_port = service._tags_port
        assert tags_port.get_tags_bulk.call_count == 1
        entity_type, entity_ids = tags_port.get_tags_bulk.call_args[0]
        assert entity_type == "cms_post"
        assert set(entity_ids) == {post.id for post in posts}

    def test_missing_tags_port_degrades_to_empty_tags(self):
        post = _post()
        service = _service([post], None, tags_port=None)  # no port wired

        result = service.list_posts(post_type="post", status="published")

        assert result["items"][0]["tags"] == []

    def test_list_by_term_also_carries_tags(self):
        post = _post()
        service = _service([post], {post.id: ["vue"]})
        service._repo.find_by_term_slug.return_value = {
            "items": [post],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }

        result = service.list_posts_by_term("category", "gadgets", post_type="post")

        assert result["items"][0]["tags"] == [
            {"slug": "vue", "name": "Vue", "archive_url": "tag/vue"}
        ]

    def test_mixed_types_group_into_bounded_bulk_calls(self):
        article = _post(slug="a", post_type="post")
        page = _post(slug="pg", post_type="page")
        tags_by_id = {article.id: ["vue"], page.id: ["docs"]}
        service = _service([article, page], tags_by_id)

        result = service.list_posts(status="published")

        # One bulk call per core entity type — bounded (<=2), never per-post.
        assert service._tags_port.get_tags_bulk.call_count == 2
        by_slug = {item["slug"]: item["tags"] for item in result["items"]}
        assert by_slug["a"] == [
            {"slug": "vue", "name": "Vue", "archive_url": "tag/vue"}
        ]
        assert by_slug["pg"] == [
            {"slug": "docs", "name": "Docs", "archive_url": "tag/docs"}
        ]
