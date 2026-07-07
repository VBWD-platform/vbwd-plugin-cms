"""Unit tests for PostService permalink wiring (S122) — MagicMock repos, no DB.

Covers the write-path transform the engine adds on top of the existing slug
seam:

* mode ``off`` → ``slug`` is used verbatim for BOTH a page and a post (the
  regression guard: the engine is inert until an operator opts in);
* ``type=post`` + structured/template → the assembled full path is stored into
  ``slug`` while ``slug_base`` keeps the post's own tail segment;
* ``type=page`` is never transformed regardless of mode;
* uniqueness suffixing (`-2`) on a computed-slug collision;
* primary-term resolution precedence (explicit-among-assigned → first assigned
  category → none);
* the auto-301 on a published slug rename (one idempotent rule; none for drafts
  or unchanged slugs);
* ``previous_slug`` presence/absence in the ``content.changed`` payload;
* the ``preview_permalink`` DRY surface behind the admin preview endpoint.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (the engine reuses the ONE renderer + the ONE canonical-URL rule);
Liskov (a null routing repo / off mode preserve today's behaviour exactly);
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from types import SimpleNamespace
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


def _term(slug, term_type="category", parent_id=None):
    return SimpleNamespace(
        id=uuid4(), slug=slug, term_type=term_type, parent_id=parent_id
    )


def _make_service(config=None, posts=None, terms=None, post_term_links=None):
    store = {str(p.id): p for p in (posts or [])}
    term_store = {str(t.id): t for t in (terms or [])}

    repo = MagicMock()
    repo.find_by_id.side_effect = lambda pid: store.get(str(pid))
    repo.find_by_type_and_slug.side_effect = lambda ptype, slug: next(
        (p for p in store.values() if p.type == ptype and p.slug == slug), None
    )

    def _save(post):
        if post.id is None:
            post.id = uuid4()
        store[str(post.id)] = post
        return post

    repo.save.side_effect = _save

    term_repo = MagicMock()
    term_repo.find_by_id.side_effect = lambda tid: term_store.get(str(tid))

    post_term_repo = MagicMock()
    links = post_term_links or {}
    post_term_repo.find_by_post.side_effect = lambda pid: [
        SimpleNamespace(term_id=tid) for tid in links.get(str(pid), [])
    ]

    routing_rule_repo = MagicMock()
    routing_rule_repo.find_by_match.return_value = []
    dispatcher = MagicMock()

    service = PostService(
        repo=repo,
        term_repo=term_repo,
        post_term_repo=post_term_repo,
        event_dispatcher=dispatcher,
        routing_rule_repo=routing_rule_repo,
        permalink_config=config,
    )
    return service, repo, dispatcher, routing_rule_repo, store


def _existing_post(post_type="post", slug="hello", slug_base=None, status="draft"):
    post = CmsPost()
    post.id = uuid4()
    post.type = post_type
    post.slug = slug
    post.slug_base = slug_base if slug_base is not None else slug
    post.title = slug.title()
    post.status = status
    post.primary_term_id = None
    post.published_at = None
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _last_event_data(dispatcher):
    return dispatcher.dispatch.call_args_list[-1].args[0].data


STRUCTURED = {
    "posts_permalink_mode": "structured",
    "posts_root": "blog",
    "posts_permalink_include_year": False,
    "posts_permalink_uncategorized_slug": "uncategorized",
}


class TestModeOffVerbatim:
    def test_post_slug_verbatim_when_mode_off(self):
        service, repo, _, _, _ = _make_service(config={"posts_permalink_mode": "off"})
        service.create_post({"type": "post", "title": "Hello World"})
        assert repo.save.call_args[0][0].slug == "hello-world"

    def test_post_slug_verbatim_when_no_config(self):
        service, repo, _, _, _ = _make_service(config=None)
        service.create_post({"type": "post", "slug": "custom/path", "title": "X"})
        assert repo.save.call_args[0][0].slug == "custom/path"

    def test_page_slug_verbatim_when_mode_off(self):
        service, repo, _, _, _ = _make_service(config={"posts_permalink_mode": "off"})
        service.create_post({"type": "page", "slug": "about/team", "title": "Team"})
        assert repo.save.call_args[0][0].slug == "about/team"


class TestPostTransform:
    def test_structured_assembles_slug_and_keeps_base(self):
        category = _term("electronics")
        service, repo, _, _, _ = _make_service(config=STRUCTURED, terms=[category])
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(category.id)],
                "primary_term_id": str(category.id),
            }
        )
        saved = repo.save.call_args[0][0]
        assert saved.slug == "blog/electronics/my-post"
        assert saved.slug_base == "my-post"
        assert str(saved.primary_term_id) == str(category.id)

    def test_template_mode_assembles(self):
        category = _term("electronics")
        # Template ordering differs from structured (category before root) so
        # this proves template mode is honoured, not structured sugar.
        config = {
            "posts_permalink_mode": "template",
            "posts_root": "blog",
            "posts_permalink_template": "%category%/%root%/%slug%",
        }
        service, repo, _, _, _ = _make_service(config=config, terms=[category])
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(category.id)],
                "primary_term_id": str(category.id),
            }
        )
        saved = repo.save.call_args[0][0]
        assert saved.slug == "electronics/blog/my-post"

    def test_page_never_transformed_even_when_mode_structured(self):
        service, repo, _, _, _ = _make_service(config=STRUCTURED)
        service.create_post({"type": "page", "slug": "about/team", "title": "Team"})
        assert repo.save.call_args[0][0].slug == "about/team"

    def test_uniqueness_suffix_on_computed_collision(self):
        category = _term("electronics")
        existing = _existing_post(post_type="post", slug="blog/electronics/my-post")
        service, repo, _, _, _ = _make_service(
            config=STRUCTURED, posts=[existing], terms=[category]
        )
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(category.id)],
                "primary_term_id": str(category.id),
            }
        )
        saved = repo.save.call_args[0][0]
        assert saved.slug == "blog/electronics/my-post-2"


class TestPrimaryTermResolution:
    def test_explicit_primary_among_assigned_wins(self):
        cat_a = _term("news")
        cat_b = _term("reviews")
        service, repo, _, _, _ = _make_service(config=STRUCTURED, terms=[cat_a, cat_b])
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(cat_a.id), str(cat_b.id)],
                "primary_term_id": str(cat_b.id),
            }
        )
        assert repo.save.call_args[0][0].slug == "blog/reviews/my-post"

    def test_first_assigned_category_when_no_explicit(self):
        cat_a = _term("news")
        cat_b = _term("reviews")
        service, repo, _, _, _ = _make_service(config=STRUCTURED, terms=[cat_a, cat_b])
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(cat_a.id), str(cat_b.id)],
            }
        )
        assert repo.save.call_args[0][0].slug == "blog/news/my-post"

    def test_no_category_uses_uncategorized(self):
        service, repo, _, _, _ = _make_service(config=STRUCTURED)
        service.create_post({"type": "post", "title": "My Post"})
        assert repo.save.call_args[0][0].slug == "blog/uncategorized/my-post"

    def test_tag_only_assignment_falls_back_to_uncategorized(self):
        tag = _term("featured", term_type="tag")
        service, repo, _, _, _ = _make_service(config=STRUCTURED, terms=[tag])
        service.create_post(
            {"type": "post", "title": "My Post", "term_ids": [str(tag.id)]}
        )
        assert repo.save.call_args[0][0].slug == "blog/uncategorized/my-post"


class TestSlugRedirect:
    def test_published_rename_emits_one_301(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/old-post",
            slug_base="old-post",
            status="published",
        )
        service, _, _, routing_repo, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        service.update_post(str(post.id), {"slug": "new-post"})

        assert routing_repo.save.call_count == 1
        rule = routing_repo.save.call_args[0][0]
        assert rule.match_type == "path_prefix"
        assert rule.match_value == "/blog/electronics/old-post"
        assert rule.target_slug == "/blog/electronics/new-post"
        assert rule.redirect_code == 301
        assert rule.is_rewrite is False

    def test_draft_rename_emits_no_301(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/old-post",
            slug_base="old-post",
            status="draft",
        )
        service, _, _, routing_repo, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        service.update_post(str(post.id), {"slug": "new-post"})
        assert routing_repo.save.call_count == 0

    def test_unchanged_slug_emits_no_301(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/my-post",
            slug_base="my-post",
            status="published",
        )
        service, _, _, routing_repo, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        service.update_post(str(post.id), {"title": "My Post"})
        assert routing_repo.save.call_count == 0

    def test_301_is_idempotent(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/old-post",
            slug_base="old-post",
            status="published",
        )
        service, _, _, routing_repo, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        # A rule already redirects the old path to the new target.
        existing_rule = SimpleNamespace(
            match_type="path_prefix",
            match_value="/blog/electronics/old-post",
            target_slug="/blog/electronics/new-post",
            redirect_code=301,
        )
        routing_repo.find_by_match.return_value = [existing_rule]
        service.update_post(str(post.id), {"slug": "new-post"})
        assert routing_repo.save.call_count == 0


class TestPreviousSlugInEvent:
    def test_previous_slug_absent_on_create(self):
        category = _term("electronics")
        service, _, dispatcher, _, _ = _make_service(
            config=STRUCTURED, terms=[category]
        )
        service.create_post(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(category.id)],
                "primary_term_id": str(category.id),
            }
        )
        assert "previous_slug" not in _last_event_data(dispatcher)

    def test_previous_slug_present_on_rename(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/old-post",
            slug_base="old-post",
            status="published",
        )
        service, _, dispatcher, _, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        service.update_post(str(post.id), {"slug": "new-post"})
        data = _last_event_data(dispatcher)
        assert data["previous_slug"] == "blog/electronics/old-post"
        assert data["slug"] == "blog/electronics/new-post"

    def test_previous_slug_absent_on_no_slug_change(self):
        category = _term("electronics")
        post = _existing_post(
            post_type="post",
            slug="blog/electronics/my-post",
            slug_base="my-post",
            status="published",
        )
        service, _, dispatcher, _, _ = _make_service(
            config=STRUCTURED,
            posts=[post],
            terms=[category],
            post_term_links={str(post.id): [str(category.id)]},
        )
        post.primary_term_id = category.id
        service.update_post(str(post.id), {"excerpt": "changed"})
        assert "previous_slug" not in _last_event_data(dispatcher)


class TestPreviewPermalink:
    def test_preview_returns_path_and_url(self):
        category = _term("electronics")
        config = dict(STRUCTURED)
        config["public_base_url"] = "https://example.test"
        service, _, _, _, _ = _make_service(config=config, terms=[category])
        result = service.preview_permalink(
            {
                "type": "post",
                "title": "My Post",
                "term_ids": [str(category.id)],
                "primary_term_id": str(category.id),
            }
        )
        assert result["path"] == "blog/electronics/my-post"
        assert result["url"] == "https://example.test/blog/electronics/my-post"

    def test_preview_page_is_verbatim(self):
        service, _, _, _, _ = _make_service(config=STRUCTURED)
        result = service.preview_permalink(
            {"type": "page", "slug": "about/team", "title": "Team"}
        )
        assert result["path"] == "about/team"
