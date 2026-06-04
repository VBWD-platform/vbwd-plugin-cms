"""Unit tests for the unified seeder helper (S47.0 increment 2).

``populate_cms.py`` seeds the unified model (cms_post / cms_term) through the
PostService / TermService — never raw SQL — and is idempotent: a second run
creates nothing new. We exercise ``seed_unified_content`` against in-memory
fake services so no DB is needed.
"""
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType
from plugins.cms.src.bin.populate_cms import seed_unified_content


class _FakePostService:
    """Honours the PostService create/slug-uniqueness contract in memory."""

    def __init__(self):
        self._by_type_slug = {}
        self.create_calls = 0

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
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
    )


class TestSeedUnifiedContent:
    def test_seeds_pages_posts_and_terms(self):
        _with_registries()
        post_service = _FakePostService()
        term_service = _FakeTermService()
        summary = seed_unified_content(post_service, term_service)
        assert summary["posts_created"] >= 2
        assert summary["terms_created"] >= 2
        # At least one page and one post type were seeded.
        types = {key[0] for key in post_service._by_type_slug}
        assert "page" in types
        assert "post" in types
        # Categories and tags both present.
        term_types = {key[0] for key in term_service._by_type_slug}
        assert "category" in term_types
        assert "tag" in term_types

    def test_second_run_creates_nothing_new(self):
        _with_registries()
        post_service = _FakePostService()
        term_service = _FakeTermService()
        seed_unified_content(post_service, term_service)
        first_posts = post_service.create_calls
        first_terms = term_service.create_calls

        second = seed_unified_content(post_service, term_service)
        assert second["posts_created"] == 0
        assert second["terms_created"] == 0
        assert post_service.create_calls == first_posts
        assert term_service.create_calls == first_terms
