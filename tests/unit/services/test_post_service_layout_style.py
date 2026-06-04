"""Unit: PostService accepts + validates layout/style (S — posts like pages).

MagicMock repos, no DB. Posts gain the same layout/style/theme-switcher
capability as pages: create/update accept the ids, persist them, serialize them,
and an unknown layout/style id is rejected (the route maps that to 400).

Engineering requirements (binding, restated): TDD-first; DI (layout/style repos
injected); narrow ports (only the lookups the validation needs); Liskov (an
absent repo means "no validation", never a silent failure); no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services.post_service import (
    PostService,
    InvalidLayoutOrStyleError,
)
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


def _post(slug="hello"):
    post = CmsPost()
    post.id = uuid4()
    post.type = "post"
    post.slug = slug
    post.title = "Hello"
    post.status = "draft"
    post.parent_id = None
    post.published_at = None
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_service(posts=None, known_layout_ids=(), known_style_ids=()):
    store = {str(p.id): p for p in (posts or [])}
    repo = MagicMock()
    repo.find_by_id.side_effect = lambda pid: store.get(str(pid))
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: next(
        (p for p in store.values() if p.type == ptype and p.slug == slug), None
    )
    repo.save.side_effect = lambda post: store.setdefault(str(post.id), post) or post

    layout_repo = MagicMock()
    layout_repo.find_by_id.side_effect = lambda lid: (
        object() if str(lid) in {str(x) for x in known_layout_ids} else None
    )
    style_repo = MagicMock()
    style_repo.find_by_id.side_effect = lambda sid: (
        object() if str(sid) in {str(x) for x in known_style_ids} else None
    )

    service = PostService(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=MagicMock(),
        event_dispatcher=MagicMock(),
        layout_repo=layout_repo,
        style_repo=style_repo,
    )
    return service, repo, store


class TestCreateWithLayoutStyle:
    def test_create_accepts_and_persists_layout_style(self):
        layout_id = str(uuid4())
        style_id = str(uuid4())
        service, repo, _ = _make_service(
            known_layout_ids=[layout_id], known_style_ids=[style_id]
        )
        result = service.create_post(
            {
                "type": "post",
                "title": "Styled",
                "layout_id": layout_id,
                "style_id": style_id,
            }
        )
        saved = repo.save.call_args[0][0]
        assert str(saved.layout_id) == layout_id
        assert str(saved.style_id) == style_id
        assert result["layout_id"] == layout_id
        assert result["style_id"] == style_id

    def test_create_unknown_layout_rejected(self):
        service, _, _ = _make_service()
        with pytest.raises(InvalidLayoutOrStyleError):
            service.create_post(
                {"type": "post", "title": "X", "layout_id": str(uuid4())}
            )

    def test_create_unknown_style_rejected(self):
        service, _, _ = _make_service()
        with pytest.raises(InvalidLayoutOrStyleError):
            service.create_post(
                {"type": "post", "title": "X", "style_id": str(uuid4())}
            )

    def test_create_without_layout_style_leaves_both_unset(self):
        service, repo, _ = _make_service()
        service.create_post({"type": "post", "title": "Plain"})
        saved = repo.save.call_args[0][0]
        assert saved.layout_id is None
        assert saved.style_id is None


class TestUpdateWithLayoutStyle:
    def test_update_sets_layout_style(self):
        post = _post()
        layout_id = str(uuid4())
        service, repo, _ = _make_service(posts=[post], known_layout_ids=[layout_id])
        result = service.update_post(str(post.id), {"layout_id": layout_id})
        assert result["layout_id"] == layout_id

    def test_update_unknown_style_rejected(self):
        post = _post()
        service, _, _ = _make_service(posts=[post])
        with pytest.raises(InvalidLayoutOrStyleError):
            service.update_post(str(post.id), {"style_id": str(uuid4())})

    def test_update_can_clear_layout(self):
        post = _post()
        post.layout_id = uuid4()
        service, repo, _ = _make_service(posts=[post])
        result = service.update_post(str(post.id), {"layout_id": None})
        assert result["layout_id"] is None
