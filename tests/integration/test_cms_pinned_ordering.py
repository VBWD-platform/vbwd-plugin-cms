"""Pinned/sticky post ordering + persistence round-trip (real PG, S-archives).

Covers the "pin a post to the top of a listing" feature end to end through the
service/repository layer:

  * a category archive floats the post pinned WITHIN that category first, ahead
    of the normal ``sort_order``/``updated_at`` order (cms_post_term.pinned);
  * the blog index floats a ``cms_post.pinned`` post first (cms_post.pinned);
  * a tag archive is UNCHANGED — a global pin never reorders it (find_by_tag_slug
    has no pinned prefix);
  * the category-assignment write round-trips ``pinned`` per category;
  * a post update round-trips ``cms_post.pinned`` and get_post hydrates both.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG
via the ``db`` fixture, cold-start clean); SOLID/DI/DRY (ordering owned by the
repository; pins written through the repo, no raw SQL); Liskov (absent pin =
False); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType


@pytest.fixture(autouse=True)
def _registries():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()
    term_type_registry.clear_term_types()


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=None,
    )


def _make_post(service, marker, name, sort_order):
    return service.create_post(
        {
            "type": "post",
            "title": name,
            "slug": f"{name}-{marker}",
            "status": POST_STATUS_PUBLISHED,
            "sort_order": sort_order,
        }
    )


class TestCategoryArchivePinnedFirst:
    def test_pinned_post_floats_to_top_of_category(self, db):
        service = _post_service(db)
        term_service = TermService(TermRepository(db.session))
        marker = uuid.uuid4().hex[:8]
        category = term_service.create_term(
            {"term_type": "category", "name": "Gadgets", "slug": f"gadgets-{marker}"}
        )

        # The pinned post gets the LARGEST sort_order, so by the normal ordering
        # (sort_order asc) it would come LAST — pinning must override that.
        first = _make_post(service, marker, "unpinned-a", sort_order=0)
        second = _make_post(service, marker, "unpinned-b", sort_order=1)
        pinned = _make_post(service, marker, "the-pinned", sort_order=99)
        for post in (first, second, pinned):
            service.assign_terms(post["id"], [category["id"]])
        # Pin only the third post within this category.
        service.assign_terms(
            pinned["id"], [category["id"]], pinned_term_ids=[category["id"]]
        )

        result = service.list_posts_by_term(
            "category", category["slug"], status=POST_STATUS_PUBLISHED
        )
        slugs = [item["slug"] for item in result["items"]]
        assert slugs[0] == pinned["slug"]
        assert set(slugs) == {first["slug"], second["slug"], pinned["slug"]}


class TestBlogIndexPinnedFirst:
    def test_globally_pinned_post_floats_to_top_of_blog_index(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:8]

        _make_post(service, marker, "idx-a", sort_order=0)
        _make_post(service, marker, "idx-b", sort_order=1)
        pinned = _make_post(service, marker, "idx-pinned", sort_order=99)
        service.update_post(pinned["id"], {"pinned": True})

        result = service.list_posts(
            post_type="post", status=POST_STATUS_PUBLISHED, per_page=100
        )
        slugs = [item["slug"] for item in result["items"]]
        assert slugs[0] == pinned["slug"]


class TestTagArchiveOrderingUnchanged:
    def test_global_pin_does_not_reorder_tag_archive(self, app, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:8]
        tag_slug = f"deals-{marker}"

        first = _make_post(service, marker, "tag-a", sort_order=0)
        # A globally-pinned post with the LARGEST sort_order: on the blog index it
        # floats first, but the tag archive must ignore the pin (sort_order wins).
        pinned = _make_post(service, marker, "tag-pinned", sort_order=99)
        service.update_post(pinned["id"], {"pinned": True})

        with app.app_context():
            tags_port = app.container.tags_and_custom_fields()
            tags_port.set_tags("cms_post", first["id"], [tag_slug])
            tags_port.set_tags("cms_post", pinned["id"], [tag_slug])

        result = service.list_posts_by_term(
            "tag", tag_slug, status=POST_STATUS_PUBLISHED
        )
        slugs = [item["slug"] for item in result["items"]]
        # Default order (sort_order asc) is preserved — the pinned post is NOT
        # floated to the top of the tag archive.
        assert slugs[0] == first["slug"]
        assert set(slugs) == {first["slug"], pinned["slug"]}


class TestPinnedRoundTrip:
    def test_category_assignment_round_trips_pinned_per_category(self, db):
        service = _post_service(db)
        term_service = TermService(TermRepository(db.session))
        marker = uuid.uuid4().hex[:8]
        pinned_cat = term_service.create_term(
            {"term_type": "category", "name": "Pinned", "slug": f"pin-{marker}"}
        )
        plain_cat = term_service.create_term(
            {"term_type": "category", "name": "Plain", "slug": f"plain-{marker}"}
        )
        post = _make_post(service, marker, "rt-post", sort_order=0)

        service.assign_terms(
            post["id"],
            [pinned_cat["id"], plain_cat["id"]],
            pinned_term_ids=[pinned_cat["id"]],
        )

        links = {
            str(link.term_id): link.pinned
            for link in PostTermRepository(db.session).find_by_post(post["id"])
        }
        assert links[str(pinned_cat["id"])] is True
        assert links[str(plain_cat["id"])] is False

        loaded = service.get_post(post["id"])
        assert loaded["pinned_term_ids"] == [str(pinned_cat["id"])]

    def test_post_update_round_trips_cms_post_pinned(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:8]
        post = _make_post(service, marker, "gp-post", sort_order=0)
        assert service.get_post(post["id"])["pinned"] is False

        service.update_post(post["id"], {"pinned": True})
        assert service.get_post(post["id"])["pinned"] is True

        service.update_post(post["id"], {"pinned": False})
        assert service.get_post(post["id"])["pinned"] is False

    def test_absent_pinned_term_ids_preserves_existing_pins(self, db):
        """A legacy caller that passes only term_ids must not drop a pin."""
        service = _post_service(db)
        term_service = TermService(TermRepository(db.session))
        marker = uuid.uuid4().hex[:8]
        category = term_service.create_term(
            {"term_type": "category", "name": "Keep", "slug": f"keep-{marker}"}
        )
        post = _make_post(service, marker, "keep-post", sort_order=0)
        service.assign_terms(
            post["id"], [category["id"]], pinned_term_ids=[category["id"]]
        )
        # Re-assign the SAME set with no pinned info (legacy signature).
        service.assign_terms(post["id"], [category["id"]])

        links = PostTermRepository(db.session).find_by_post(post["id"])
        assert links[0].pinned is True
