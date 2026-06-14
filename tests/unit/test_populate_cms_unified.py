"""Unit tests for the unified seeder helper (S47.0 increment 2).

``populate_cms.py`` seeds the unified model (cms_post / cms_term) through the
PostService / TermService — never raw SQL — and is idempotent: a second run
creates nothing new. We exercise ``seed_unified_content`` against in-memory
fake services so no DB is needed.

D7: categories stay on the cms_term taxonomy; tags are seeded onto the core tag
catalog via the tags port (``set_tags`` on ``cms_post``), no longer as
``cms_term('tag')`` rows.
"""
from unittest.mock import MagicMock

from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType
from plugins.cms.src.bin.populate_cms import seed_unified_content


class _FakePostService:
    """Honours the PostService create/slug-uniqueness contract in memory."""

    def __init__(self):
        self._by_type_slug = {}
        self.create_calls = 0
        self.assigned_terms = {}

    def create_post(self, data):
        key = (data["type"], data["slug"])
        if key in self._by_type_slug:
            from plugins.cms.src.services.post_service import PostSlugConflictError

            raise PostSlugConflictError(f"{key} exists")
        self.create_calls += 1
        record = {"id": str(len(self._by_type_slug) + 1), **data}
        self._by_type_slug[key] = record
        return record

    def resolve_published_path(self, post_type, path):
        return self._by_type_slug.get((post_type, path.strip("/")))

    def assign_terms(self, post_id, term_ids):
        # Mirrors PostService.assign_terms: replaces the post's term set.
        self.assigned_terms[post_id] = list(term_ids)


class _FakeTermService:
    def __init__(self):
        self._by_type_slug = {}
        self.create_calls = 0

    def create_term(self, data):
        key = (data["term_type"], data["slug"])
        if key in self._by_type_slug:
            from plugins.cms.src.services.term_service import TermSlugConflictError

            raise TermSlugConflictError(f"{key} exists")
        self.create_calls += 1
        record = {"id": str(len(self._by_type_slug) + 1), **data}
        self._by_type_slug[key] = record
        return record

    def list_terms(self, term_type):
        return [
            value for (t, _slug), value in self._by_type_slug.items() if t == term_type
        ]


def _with_registries():
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
    # ``tag`` is no longer a cms_term type (D7).


class TestSeedUnifiedContent:
    def test_seeds_pages_posts_and_category_terms(self):
        _with_registries()
        post_service = _FakePostService()
        term_service = _FakeTermService()
        summary = seed_unified_content(post_service, term_service, MagicMock())
        assert summary["posts_created"] >= 2
        assert summary["terms_created"] >= 2
        # At least one page and one post type were seeded.
        types = {key[0] for key in post_service._by_type_slug}
        assert "page" in types
        assert "post" in types
        # Only categories live on the cms_term taxonomy now — no tag terms.
        term_types = {key[0] for key in term_service._by_type_slug}
        assert "category" in term_types
        assert "tag" not in term_types

    def test_second_run_creates_nothing_new(self):
        _with_registries()
        post_service = _FakePostService()
        term_service = _FakeTermService()
        seed_unified_content(post_service, term_service, MagicMock())
        first_posts = post_service.create_calls
        first_terms = term_service.create_calls

        second = seed_unified_content(post_service, term_service, MagicMock())
        assert second["posts_created"] == 0
        assert second["terms_created"] == 0
        assert post_service.create_calls == first_posts
        assert term_service.create_calls == first_terms

    def test_links_hello_world_tags_via_core_port(self):
        _with_registries()
        post_service = _FakePostService()
        term_service = _FakeTermService()
        tags_port = MagicMock()
        summary = seed_unified_content(post_service, term_service, tags_port)

        # Both tags (release, tutorial) are set on hello-world via the core port.
        assert summary["tags_linked"] == 2
        hello = post_service.resolve_published_path("post", "hello-world")
        tags_port.set_tags.assert_called_with(
            "cms_post", hello["id"], ["release", "tutorial"]
        )
        # Categories are NOT routed through assign_terms-as-tags (no tag terms).
        assert "tag" not in {key[0] for key in term_service._by_type_slug}
