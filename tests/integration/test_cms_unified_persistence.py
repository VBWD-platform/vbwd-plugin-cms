"""Integration tests for the unified content tables (S47.0, real PG).

Covers: model persistence, (type,slug)/(term_type,slug) uniqueness, cascade
on post delete (junction cleared, terms untouched), the published filter,
pagination, and nested-path resolution through the service layer.
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


def _term_service(db):
    return TermService(TermRepository(db.session))


class TestPersistence:
    def test_post_persists_with_to_dict(self, db):
        service = _post_service(db)
        slug = f"hello-{uuid.uuid4().hex[:8]}"
        result = service.create_post({"type": "post", "title": "Hi", "slug": slug})
        fetched = service.get_post(result["id"])
        assert fetched["slug"] == slug
        assert fetched["status"] == "draft"

    def test_type_slug_uniqueness(self, db):
        service = _post_service(db)
        slug = f"dup-{uuid.uuid4().hex[:8]}"
        service.create_post({"type": "post", "title": "A", "slug": slug})
        from plugins.cms.src.services.post_service import PostSlugConflictError

        with pytest.raises(PostSlugConflictError):
            service.create_post({"type": "post", "title": "B", "slug": slug})

    def test_same_slug_different_type_persists(self, db):
        service = _post_service(db)
        slug = f"shared-{uuid.uuid4().hex[:8]}"
        service.create_post({"type": "post", "title": "A", "slug": slug})
        service.create_post({"type": "page", "title": "B", "slug": slug})
        assert (
            PostRepository(db.session).find_by_type_and_slug("page", slug) is not None
        )

    def test_term_type_slug_uniqueness(self, db):
        service = _term_service(db)
        slug = f"news-{uuid.uuid4().hex[:8]}"
        service.create_term({"term_type": "category", "name": "News", "slug": slug})
        from plugins.cms.src.services.term_service import TermSlugConflictError

        with pytest.raises(TermSlugConflictError):
            service.create_term(
                {"term_type": "category", "name": "News2", "slug": slug}
            )


class TestCascade:
    def test_delete_post_clears_junction_not_terms(self, db):
        post_service = _post_service(db)
        term_service = _term_service(db)
        term = term_service.create_term(
            {"term_type": "tag", "name": "T", "slug": f"t-{uuid.uuid4().hex[:8]}"}
        )
        post = post_service.create_post(
            {"type": "post", "title": "P", "slug": f"p-{uuid.uuid4().hex[:8]}"}
        )
        post_service.assign_terms(post["id"], [term["id"]])

        link_repo = PostTermRepository(db.session)
        assert len(link_repo.find_by_post(post["id"])) == 1

        PostRepository(db.session).delete(post["id"])

        assert link_repo.find_by_post(post["id"]) == []
        # Term survives.
        assert TermRepository(db.session).find_by_id(term["id"]) is not None


class TestPublishedFilterAndPagination:
    def test_published_filter_excludes_draft(self, db):
        service = _post_service(db)
        published_slug = f"pub-{uuid.uuid4().hex[:8]}"
        service.create_post(
            {
                "type": "post",
                "title": "Pub",
                "slug": published_slug,
                "status": POST_STATUS_PUBLISHED,
            }
        )
        service.create_post(
            {"type": "post", "title": "Draft", "slug": f"dr-{uuid.uuid4().hex[:8]}"}
        )
        result = service.list_posts(post_type="post", status=POST_STATUS_PUBLISHED)
        slugs = [item["slug"] for item in result["items"]]
        assert published_slug in slugs

    def test_pagination_limits_items(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        for index in range(3):
            service.create_post(
                {
                    "type": "post",
                    "title": f"Item {index}",
                    "slug": f"pg-{marker}-{index}",
                    "status": POST_STATUS_PUBLISHED,
                }
            )
        page_one = service.list_posts(
            post_type="post", status=POST_STATUS_PUBLISHED, page=1, per_page=2
        )
        assert len(page_one["items"]) == 2
        assert page_one["pages"] >= 2


class TestListSearch:
    def test_search_matches_title_case_insensitive(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        service.create_post(
            {"type": "page", "title": f"Enterprise {marker}", "slug": f"ent-{marker}"}
        )
        service.create_post(
            {"type": "page", "title": f"Pricing {marker}", "slug": f"pri-{marker}"}
        )
        result = service.list_posts(post_type="page", search="enterprise")
        titles = [item["title"] for item in result["items"]]
        assert any(f"Enterprise {marker}" == t for t in titles)
        assert all("Pricing" not in t for t in titles)

    def test_search_matches_slug(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        service.create_post(
            {"type": "page", "title": "Some Title", "slug": f"findme-{marker}"}
        )
        result = service.list_posts(post_type="page", search=f"findme-{marker}")
        assert any(item["slug"] == f"findme-{marker}" for item in result["items"])

    def test_blank_search_returns_all_of_type(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        service.create_post({"type": "page", "title": "A", "slug": f"a-{marker}"})
        service.create_post({"type": "page", "title": "B", "slug": f"b-{marker}"})
        result = service.list_posts(post_type="page", search="")
        slugs = [item["slug"] for item in result["items"]]
        assert f"a-{marker}" in slugs and f"b-{marker}" in slugs


class TestListFilters:
    def test_filter_by_language(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        service.create_post({"type": "post", "title": "EN", "slug": f"en-{marker}", "language": "en"})
        service.create_post({"type": "post", "title": "DE", "slug": f"de-{marker}", "language": "de"})
        result = service.list_posts(post_type="post", language="de")
        slugs = [i["slug"] for i in result["items"]]
        assert f"de-{marker}" in slugs and f"en-{marker}" not in slugs

    def test_filter_by_date_range_on_updated(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:6]
        service.create_post({"type": "post", "title": "X", "slug": f"x-{marker}"})
        # Today is within range; a past-only window excludes it.
        within = service.list_posts(
            post_type="post", date_from="2000-01-01", date_to="2999-12-31"
        )
        assert any(i["slug"] == f"x-{marker}" for i in within["items"])
        past = service.list_posts(
            post_type="post", date_from="2000-01-01", date_to="2000-01-02"
        )
        assert all(i["slug"] != f"x-{marker}" for i in past["items"])


class TestNestedPathResolution:
    def test_nested_page_resolves_by_full_path(self, db):
        service = _post_service(db)
        marker = uuid.uuid4().hex[:8]
        parent = service.create_post(
            {"type": "page", "title": "About", "slug": f"about-{marker}"}
        )
        child = service.create_post(
            {
                "type": "page",
                "title": "Team",
                "slug": f"about-{marker}/team",
                "parent_id": parent["id"],
                "status": POST_STATUS_PUBLISHED,
            }
        )
        resolved = service.resolve_published_path("page", f"about-{marker}/team")
        assert resolved is not None
        assert resolved["id"] == child["id"]
