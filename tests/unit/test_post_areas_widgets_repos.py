"""Unit tests for the S55 post-area repos + PostService content-block apply.

MagicMock sessions/repos — no DB. Restated engineering requirements: TDD-first;
SOLID/DI/DRY; Liskov (the post repos honour the same contract as the page
repos); no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.repositories.cms_post_widget_repository import (
    CmsPostWidgetRepository,
)
from plugins.cms.src.repositories.cms_post_content_block_repository import (
    CmsPostContentBlockRepository,
)
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
    yield
    clear_post_types()


class _QueryStub:
    """Minimal SQLAlchemy query stub recording delete/order behaviour."""

    def __init__(self, rows):
        self._rows = rows
        self.deleted = False

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def delete(self, synchronize_session=None):
        self.deleted = True
        return len(self._rows)

    def all(self):
        return self._rows


class TestPostWidgetRepository:
    def test_replace_for_post_deletes_then_inserts(self):
        session = MagicMock()
        session.query.return_value = _QueryStub([])
        repo = CmsPostWidgetRepository(session)
        post_id = str(uuid4())

        created = repo.replace_for_post(
            post_id,
            [
                {"widget_id": str(uuid4()), "area_name": "sidebar", "sort_order": 1},
                {"widget_id": str(uuid4()), "area_name": "sidebar", "sort_order": 2},
            ],
        )

        assert len(created) == 2
        assert session.add.call_count == 2
        session.commit.assert_called_once()
        # The delete-before-insert contract: query(...).delete() ran.
        assert session.query.return_value.deleted is True
        assert all(w.post_id == post_id for w in created)

    def test_replace_for_post_persists_config_override(self):
        session = MagicMock()
        session.query.return_value = _QueryStub([])
        repo = CmsPostWidgetRepository(session)

        created = repo.replace_for_post(
            str(uuid4()),
            [
                {
                    "widget_id": str(uuid4()),
                    "area_name": "sidebar",
                    "config_override": {"title": "Per page"},
                },
                {
                    "widget_id": str(uuid4()),
                    "area_name": "footer",
                    # No override -> defaults to None (use widget default).
                },
            ],
        )

        assert created[0].config_override == {"title": "Per page"}
        assert created[1].config_override is None

    def test_to_dict_includes_config_override(self):
        from plugins.cms.src.models.cms_post_widget import CmsPostWidget

        post_widget = CmsPostWidget()
        post_widget.id = uuid4()
        post_widget.post_id = uuid4()
        post_widget.widget_id = uuid4()
        post_widget.area_name = "sidebar"
        post_widget.sort_order = 0
        post_widget.required_access_level_ids = []
        post_widget.config_override = {"heading": "Override"}
        post_widget.created_at = None

        serialized = post_widget.to_dict()
        assert serialized["config_override"] == {"heading": "Override"}

    def test_to_dict_config_override_defaults_to_none(self):
        from plugins.cms.src.models.cms_post_widget import CmsPostWidget

        post_widget = CmsPostWidget()
        post_widget.id = uuid4()
        post_widget.post_id = uuid4()
        post_widget.widget_id = uuid4()
        post_widget.area_name = "sidebar"
        post_widget.sort_order = 0
        post_widget.required_access_level_ids = []
        post_widget.created_at = None

        assert post_widget.to_dict()["config_override"] is None

    def test_find_by_post_orders_by_sort_order(self):
        session = MagicMock()
        query = _QueryStub(["row-a", "row-b"])
        session.query.return_value = query
        order_spy = MagicMock(wraps=query.order_by)
        query.order_by = order_spy
        repo = CmsPostWidgetRepository(session)

        result = repo.find_by_post(str(uuid4()))

        assert result == ["row-a", "row-b"]
        order_spy.assert_called_once()


class TestPostContentBlockRepository:
    def test_upsert_updates_existing_area_inserts_new(self):
        session = MagicMock()
        post_id = str(uuid4())
        existing = MagicMock()
        existing.area_name = "sidebar-content"
        existing.content_html = "old"
        # find_by_post returns the existing block for the upsert lookup.
        query = _QueryStub([existing])
        session.query.return_value = query
        repo = CmsPostContentBlockRepository(session)

        result = repo.replace_for_post(
            post_id,
            [
                {"area_name": "sidebar-content", "content_html": "new"},
                {"area_name": "content-above", "content_html": "fresh"},
            ],
        )

        # Existing area updated in place (no new row added for it).
        assert existing.content_html == "new"
        # Exactly one new row added (content-above).
        assert session.add.call_count == 1
        session.commit.assert_called_once()
        assert len(result) == 2


def _make_post():
    post = CmsPost()
    post.id = uuid4()
    post.type = "post"
    post.slug = "hello"
    post.title = "Hello"
    post.status = "draft"
    post.content_html = "<p>primary body</p>"
    post.content_json = {}
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _service_with_post(post, content_block_repo=None):
    repo = MagicMock()
    repo.find_by_id.side_effect = lambda pid: post if str(pid) == str(post.id) else None
    repo.find_by_type_and_slug.return_value = None
    repo.save.return_value = None
    post_term_repo = MagicMock()
    post_term_repo.find_by_post.return_value = []
    return PostService(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=post_term_repo,
        content_block_repo=content_block_repo,
    )


class TestPostServiceContentBlocks:
    def test_update_applies_content_blocks_and_leaves_primary_untouched(self):
        post = _make_post()
        block_repo = MagicMock()
        service = _service_with_post(post, content_block_repo=block_repo)

        service.update_post(
            str(post.id),
            {
                "content_blocks": [
                    {"area_name": "sidebar-content", "content_html": "<p>aside</p>"}
                ]
            },
        )

        # Primary content body is NOT overwritten by the block apply.
        assert post.content_html == "<p>primary body</p>"
        block_repo.replace_for_post.assert_called_once()
        args = block_repo.replace_for_post.call_args[0]
        assert args[0] == str(post.id)
        assert args[1][0]["area_name"] == "sidebar-content"

    def test_update_without_block_repo_is_inert(self):
        post = _make_post()
        service = _service_with_post(post, content_block_repo=None)
        # No repo wired -> must not raise even with content_blocks present.
        service.update_post(
            str(post.id),
            {"content_blocks": [{"area_name": "x", "content_html": "y"}]},
        )
        assert post.content_html == "<p>primary body</p>"

    def test_create_applies_content_blocks(self):
        post = _make_post()
        block_repo = MagicMock()
        repo = MagicMock()
        repo.find_by_type_and_slug.return_value = None

        def _save(saved_post):
            saved_post.id = post.id

        repo.save.side_effect = _save
        service = PostService(
            repo=repo,
            term_repo=MagicMock(),
            post_term_repo=MagicMock(),
            content_block_repo=block_repo,
        )

        service.create_post(
            {
                "type": "post",
                "title": "New",
                "slug": "new",
                "content_html": "<p>main</p>",
                "content_blocks": [
                    {"area_name": "content-below", "content_html": "<p>more</p>"}
                ],
            }
        )

        block_repo.replace_for_post.assert_called_once()
