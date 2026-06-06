"""Unit tests for PostService (S47.0) — MagicMock repos, no DB.

Covers: type validation via the registry (fail-fast on unknown), slug
uniqueness within type, status-transition validation, hierarchy validation
(parent rejected for non-hierarchical types, parent must be hierarchical,
cycles refused), the scheduled→published tick, term assignment, and the
`content.changed` hook firing on every status change and content edit.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services.post_service import (
    PostService,
    PostNotFoundError,
    PostSlugConflictError,
    UnknownPostTypeError,
    InvalidStatusTransitionError,
    PostHierarchyError,
)
from plugins.cms.src.services.post_type_registry import (
    PostType,
    register_post_type,
    clear_post_types,
)


CONTENT_CHANGED = "content.changed"


@pytest.fixture(autouse=True)
def _registry():
    clear_post_types()
    register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    clear_post_types()


def _post(post_type="post", slug="hello", status="draft", parent_id=None):
    post = CmsPost()
    post.id = uuid4()
    post.type = post_type
    post.slug = slug
    post.title = slug.title()
    post.status = status
    post.parent_id = parent_id
    post.published_at = None
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_service(posts=None):
    store = {str(p.id): p for p in (posts or [])}
    repo = MagicMock()
    repo.find_by_id.side_effect = lambda pid: store.get(str(pid))
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: next(
        (p for p in store.values() if p.type == ptype and p.slug == slug), None
    )

    def _save(post):
        store[str(post.id)] = post
        return post

    repo.save.side_effect = _save
    repo.find_scheduled_due.return_value = []
    term_repo = MagicMock()
    post_term_repo = MagicMock()
    dispatcher = MagicMock()
    service = PostService(
        repo=repo,
        term_repo=term_repo,
        post_term_repo=post_term_repo,
        event_dispatcher=dispatcher,
    )
    return service, repo, dispatcher, store


def _dispatched_names(dispatcher):
    return [call.args[0].name for call in dispatcher.dispatch.call_args_list]


class TestCreatePost:
    def test_create_unknown_type_fails_fast(self):
        service, _, _, _ = _make_service()
        with pytest.raises(UnknownPostTypeError):
            service.create_post({"type": "event", "title": "X"})

    def test_create_known_type_succeeds_and_defaults_draft(self):
        service, repo, _, _ = _make_service()
        result = service.create_post({"type": "post", "title": "Hello World"})
        repo.save.assert_called_once()
        assert result["type"] == "post"
        assert result["status"] == "draft"

    def test_create_auto_slugifies_title(self):
        service, repo, _, _ = _make_service()
        service.create_post({"type": "post", "title": "Hello World"})
        assert repo.save.call_args[0][0].slug == "hello-world"

    def test_create_duplicate_slug_within_type_conflicts(self):
        existing = _post(post_type="post", slug="hello-world")
        service, _, _, _ = _make_service(posts=[existing])
        with pytest.raises(PostSlugConflictError):
            service.create_post({"type": "post", "title": "Hello World"})

    def test_same_slug_different_type_is_allowed(self):
        existing = _post(post_type="page", slug="hello-world")
        service, repo, _, _ = _make_service(posts=[existing])
        service.create_post({"type": "post", "title": "Hello World"})
        repo.save.assert_called_once()

    def test_create_fires_content_changed(self):
        service, _, dispatcher, _ = _make_service()
        service.create_post({"type": "post", "title": "Hello"})
        assert CONTENT_CHANGED in _dispatched_names(dispatcher)


class TestPreviewToken:
    def test_create_generates_preview_token(self):
        service, repo, _, _ = _make_service()
        result = service.create_post({"type": "post", "title": "P"})
        assert result["preview_token"]
        assert len(result["preview_token"]) >= 16

    def test_get_post_backfills_missing_preview_token(self):
        post = _post()
        post.preview_token = None
        service, repo, _, _ = _make_service(posts=[post])
        dto = service.get_post(str(post.id))
        assert dto["preview_token"]
        assert post.preview_token == dto["preview_token"]

    def test_get_post_keeps_existing_preview_token(self):
        post = _post()
        post.preview_token = "fixed-token"
        service, _, _, _ = _make_service(posts=[post])
        assert service.get_post(str(post.id))["preview_token"] == "fixed-token"


class TestBulkOps:
    def test_bulk_delete(self):
        service, repo, _, _ = _make_service()
        repo.bulk_delete.return_value = 3
        assert service.bulk_delete(["a", "b", "c"]) == {"deleted": 3}
        repo.bulk_delete.assert_called_once_with(["a", "b", "c"])

    def test_bulk_set_status_publishes_draft_posts(self):
        posts = [_post(slug="a", status="draft"), _post(slug="b", status="draft")]
        service, repo, _, _ = _make_service(posts=posts)
        repo.find_by_ids.return_value = posts
        result = service.bulk_set_status([str(p.id) for p in posts], "published")
        assert result == {"updated": 2}
        assert all(p.status == "published" for p in posts)

    def test_bulk_set_status_skips_illegal_transitions(self):
        # published → pending is illegal → skipped, not raised.
        published = _post(slug="t", status="published")
        service, repo, _, _ = _make_service(posts=[published])
        repo.find_by_ids.return_value = [published]
        assert service.bulk_set_status([str(published.id)], "pending") == {"updated": 0}

    def test_bulk_set_searchable_toggles_seo_excluded(self):
        post = _post()
        service, repo, _, _ = _make_service(posts=[post])
        repo.find_by_ids.return_value = [post]
        service.bulk_set_searchable([str(post.id)], False)
        assert post.seo_excluded is True
        service.bulk_set_searchable([str(post.id)], True)
        assert post.seo_excluded is False

    def test_bulk_assign_term_adds_without_dropping_existing(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        existing = MagicMock()
        existing.term_id = "tag-1"
        service._post_term_repo.find_by_post.return_value = [existing]
        result = service.bulk_assign_term([str(post.id)], "cat-9")
        assert result == {"updated": 1}
        # replaced with the union (existing tag + new category)
        args = service._post_term_repo.replace_for_post.call_args[0]
        assert "tag-1" in args[1] and "cat-9" in args[1]

    def test_bulk_assign_term_skips_when_already_present(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        existing = MagicMock()
        existing.term_id = "cat-9"
        service._post_term_repo.find_by_post.return_value = [existing]
        assert service.bulk_assign_term([str(post.id)], "cat-9") == {"updated": 0}


class TestRegeneratePrerender:
    def test_regenerate_emits_content_changed_for_each_published(self):
        published = [_post(slug="a", status="published"), _post(slug="b", status="published")]
        service, repo, dispatcher, _ = _make_service(posts=published)
        repo.find_all_published.return_value = published

        count = service.regenerate_prerender()

        assert count == 2
        names = _dispatched_names(dispatcher)
        assert names.count(CONTENT_CHANGED) == 2

    def test_regenerate_returns_zero_when_no_published(self):
        service, repo, _, _ = _make_service()
        repo.find_all_published.return_value = []
        assert service.regenerate_prerender() == 0


class TestTermIds:
    def test_get_post_includes_term_ids(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        link = MagicMock()
        link.term_id = "cat-1"
        service._post_term_repo.find_by_post.return_value = [link]
        dto = service.get_post(str(post.id))
        assert dto["term_ids"] == ["cat-1"]

    def test_get_post_term_ids_empty_when_none(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        service._post_term_repo.find_by_post.return_value = []
        assert service.get_post(str(post.id))["term_ids"] == []

    def test_list_posts_items_include_term_ids(self):
        post = _post()
        service, repo, _, _ = _make_service(posts=[post])
        repo.find_paginated.return_value = {
            "items": [post], "total": 1, "page": 1, "per_page": 20, "pages": 1,
        }
        link = MagicMock()
        link.term_id = "tag-9"
        service._post_term_repo.find_by_post.return_value = [link]
        result = service.list_posts(post_type="post")
        assert result["items"][0]["term_ids"] == ["tag-9"]


class TestFeaturedImage:
    def test_create_persists_featured_image_url(self):
        service, repo, _, _ = _make_service()
        result = service.create_post(
            {"type": "post", "title": "P", "featured_image_url": "/uploads/a.jpg"}
        )
        assert repo.save.call_args[0][0].featured_image_url == "/uploads/a.jpg"
        assert result["featured_image_url"] == "/uploads/a.jpg"

    def test_update_sets_featured_image_url(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        result = service.update_post(
            str(post.id), {"featured_image_url": "/uploads/b.png"}
        )
        assert result["featured_image_url"] == "/uploads/b.png"

    def test_update_can_clear_featured_image_url(self):
        post = _post()
        post.featured_image_url = "/uploads/old.jpg"
        service, _, _, _ = _make_service(posts=[post])
        result = service.update_post(str(post.id), {"featured_image_url": None})
        assert result["featured_image_url"] is None


class TestListSearch:
    def _service_with_paginated(self):
        service, repo, _, _ = _make_service()
        repo.find_paginated.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }
        return service, repo

    def test_list_posts_forwards_search_to_repo(self):
        service, repo = self._service_with_paginated()
        service.list_posts(post_type="page", search="enterprise")
        assert repo.find_paginated.call_args.kwargs["search"] == "enterprise"

    def test_list_posts_blank_search_forwarded_as_none(self):
        service, repo = self._service_with_paginated()
        service.list_posts(post_type="page", search="")
        # empty string is normalized away so the repo applies no text filter
        assert repo.find_paginated.call_args.kwargs["search"] is None

    def test_list_posts_default_search_is_none(self):
        service, repo = self._service_with_paginated()
        service.list_posts(post_type="post")
        assert repo.find_paginated.call_args.kwargs["search"] is None

    def test_list_posts_forwards_all_filters(self):
        service, repo = self._service_with_paginated()
        service.list_posts(
            post_type="page",
            language="de",
            term_id="cat-1",
            layout_id="lay-1",
            style_id="sty-1",
            date_from="2026-01-01",
            date_to="2026-12-31",
        )
        kwargs = repo.find_paginated.call_args.kwargs
        assert kwargs["language"] == "de"
        assert kwargs["term_id"] == "cat-1"
        assert kwargs["layout_id"] == "lay-1"
        assert kwargs["style_id"] == "sty-1"
        assert kwargs["date_from"] == "2026-01-01"
        assert kwargs["date_to"] == "2026-12-31"

    def test_list_posts_blank_filters_normalized_to_none(self):
        service, repo = self._service_with_paginated()
        service.list_posts(post_type="page", language="", layout_id="")
        kwargs = repo.find_paginated.call_args.kwargs
        assert kwargs["language"] is None
        assert kwargs["layout_id"] is None


class TestHierarchy:
    def test_parent_rejected_for_non_hierarchical_type(self):
        parent = _post(post_type="page", slug="about")
        service, _, _, _ = _make_service(posts=[parent])
        with pytest.raises(PostHierarchyError):
            service.create_post(
                {"type": "post", "title": "Child", "parent_id": str(parent.id)}
            )

    def test_parent_accepted_for_hierarchical_type(self):
        parent = _post(post_type="page", slug="about")
        service, repo, _, _ = _make_service(posts=[parent])
        service.create_post(
            {"type": "page", "title": "Team", "parent_id": str(parent.id)}
        )
        saved = repo.save.call_args[0][0]
        assert str(saved.parent_id) == str(parent.id)

    def test_parent_must_be_hierarchical_type_post(self):
        # A 'post' (non-hierarchical) cannot be a parent even of a page.
        parent = _post(post_type="post", slug="news")
        service, _, _, _ = _make_service(posts=[parent])
        with pytest.raises(PostHierarchyError):
            service.create_post(
                {"type": "page", "title": "Team", "parent_id": str(parent.id)}
            )

    def test_unknown_parent_rejected(self):
        service, _, _, _ = _make_service()
        with pytest.raises(PostHierarchyError):
            service.create_post(
                {"type": "page", "title": "Team", "parent_id": str(uuid4())}
            )

    def test_self_parent_cycle_refused(self):
        page = _post(post_type="page", slug="about")
        service, _, _, _ = _make_service(posts=[page])
        with pytest.raises(PostHierarchyError):
            service.update_post(str(page.id), {"parent_id": str(page.id)})

    def test_ancestor_cycle_refused(self):
        grandparent = _post(post_type="page", slug="a")
        parent = _post(post_type="page", slug="b", parent_id=grandparent.id)
        child = _post(post_type="page", slug="c", parent_id=parent.id)
        service, _, _, _ = _make_service(posts=[grandparent, parent, child])
        # Making the grandparent a child of its own descendant is a cycle.
        with pytest.raises(PostHierarchyError):
            service.update_post(str(grandparent.id), {"parent_id": str(child.id)})


class TestStatusTransitions:
    def test_legal_draft_to_pending(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        result = service.change_status(str(post.id), "pending")
        assert result["status"] == "pending"

    def test_legal_pending_to_published_sets_published_at(self):
        post = _post(status="pending")
        service, _, _, _ = _make_service(posts=[post])
        result = service.change_status(str(post.id), "published")
        assert result["status"] == "published"
        assert result["published_at"] is not None

    def test_published_to_private(self):
        post = _post(status="published")
        service, _, _, _ = _make_service(posts=[post])
        assert service.change_status(str(post.id), "private")["status"] == "private"

    def test_any_status_to_trash(self):
        post = _post(status="published")
        service, _, _, _ = _make_service(posts=[post])
        assert service.change_status(str(post.id), "trash")["status"] == "trash"

    def test_trash_can_be_restored_to_published(self):
        # A trashed post is restorable (undo delete).
        post = _post(status="trash")
        service, _, _, _ = _make_service(posts=[post])
        assert service.change_status(str(post.id), "published")["status"] == "published"

    def test_illegal_transition_rejected(self):
        # published → pending is not a legal move (published → {private, draft}).
        post = _post(status="published")
        service, _, _, _ = _make_service(posts=[post])
        with pytest.raises(InvalidStatusTransitionError):
            service.change_status(str(post.id), "pending")

    def test_unknown_target_status_rejected(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        with pytest.raises(InvalidStatusTransitionError):
            service.change_status(str(post.id), "archived")

    def test_status_change_fires_content_changed(self):
        post = _post(status="draft")
        service, _, dispatcher, _ = _make_service(posts=[post])
        service.change_status(str(post.id), "pending")
        assert CONTENT_CHANGED in _dispatched_names(dispatcher)

    def test_change_status_missing_post_raises(self):
        service, _, _, _ = _make_service()
        with pytest.raises(PostNotFoundError):
            service.change_status(str(uuid4()), "published")

    # ── status via update_post (the editor's Save path) ──────────────────────
    def test_update_post_applies_status_change(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        result = service.update_post(str(post.id), {"status": "published"})
        assert result["status"] == "published"
        assert result["published_at"] is not None

    def test_update_post_status_to_pending(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        result = service.update_post(str(post.id), {"title": "X", "status": "pending"})
        assert result["status"] == "pending"

    def test_update_post_same_status_is_noop(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        result = service.update_post(str(post.id), {"status": "draft"})
        assert result["status"] == "draft"

    def test_update_post_illegal_status_transition_rejected(self):
        post = _post(status="published")
        service, _, _, _ = _make_service(posts=[post])
        with pytest.raises(InvalidStatusTransitionError):
            service.update_post(str(post.id), {"status": "pending"})

    def test_update_post_restores_trashed_to_published(self):
        post = _post(status="trash")
        service, _, _, _ = _make_service(posts=[post])
        assert service.update_post(str(post.id), {"status": "published"})["status"] == "published"

    def test_update_post_persists_published_at_for_scheduled(self):
        post = _post(status="draft")
        service, _, _, _ = _make_service(posts=[post])
        when = "2099-01-01T10:00:00+00:00"
        result = service.update_post(
            str(post.id), {"status": "scheduled", "published_at": when}
        )
        assert result["status"] == "scheduled"
        assert result["published_at"] is not None


class TestScheduledPublishTick:
    def test_tick_publishes_due_scheduled_posts(self):
        past = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        post = _post(status="scheduled")
        post.published_at = past
        service, repo, dispatcher, _ = _make_service(posts=[post])
        repo.find_scheduled_due.return_value = [post]

        published_ids = service.publish_due_scheduled()

        assert str(post.id) in published_ids
        assert post.status == "published"
        assert CONTENT_CHANGED in _dispatched_names(dispatcher)

    def test_tick_with_nothing_due_publishes_nothing(self):
        service, repo, dispatcher, _ = _make_service()
        repo.find_scheduled_due.return_value = []
        assert service.publish_due_scheduled() == []
        dispatcher.dispatch.assert_not_called()


class TestContentEdit:
    def test_update_content_fires_content_changed(self):
        post = _post(status="published")
        service, _, dispatcher, _ = _make_service(posts=[post])
        service.update_post(str(post.id), {"title": "New Title"})
        assert CONTENT_CHANGED in _dispatched_names(dispatcher)

    def test_update_duplicate_slug_within_type_conflicts(self):
        first = _post(post_type="post", slug="one")
        second = _post(post_type="post", slug="two")
        service, _, _, _ = _make_service(posts=[first, second])
        with pytest.raises(PostSlugConflictError):
            service.update_post(str(second.id), {"slug": "one"})


class TestAssignTerms:
    def test_assign_terms_replaces_links(self):
        post = _post()
        service, _, _, _ = _make_service(posts=[post])
        term_id = str(uuid4())
        service.assign_terms(str(post.id), [term_id])
        service._post_term_repo.replace_for_post.assert_called_once_with(
            str(post.id), [term_id]
        )
