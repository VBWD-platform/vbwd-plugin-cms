"""Integration tests for Postgres FTS search (S47.4, real PG).

Exercises the real generated ``search_vector`` column + GIN index through
SearchRepository / SearchService on a seeded set:
  - matches title / excerpt / body (content_html);
  - ranks more-relevant posts higher (ts_rank);
  - excludes non-published posts;
  - narrows by ``type`` and by term (category) filter;
  - blank query yields an empty result;
  - the GIN index is actually used (EXPLAIN).
"""
import uuid

import pytest
from sqlalchemy import text

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED, POST_STATUS_DRAFT
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.search_repository import SearchRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services.search_service import SearchService
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


def _search_service(db):
    return SearchService(repo=SearchRepository(db.session))


@pytest.fixture
def seeded(db):
    """Seed a small, marker-scoped corpus and return (marker, ids)."""
    marker = uuid.uuid4().hex[:8]
    post_service = _post_service(db)
    term_service = TermService(TermRepository(db.session))

    news = term_service.create_term(
        {"term_type": "category", "name": "News", "slug": f"news-{marker}"}
    )

    title_match = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality industry {marker}",
            "slug": f"hosp-title-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    body_match = post_service.create_post(
        {
            "type": "post",
            "title": f"Unrelated heading {marker}",
            "slug": f"hosp-body-{marker}",
            "content_html": (
                f"<p>A long article about <b>hospitality</b> staffing {marker}.</p>"
            ),
            "status": POST_STATUS_PUBLISHED,
        }
    )
    excerpt_match = post_service.create_post(
        {
            "type": "post",
            "title": f"Other {marker}",
            "slug": f"hosp-excerpt-{marker}",
            "excerpt": f"hospitality excerpt {marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    draft_match = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality draft {marker}",
            "slug": f"hosp-draft-{marker}",
            "status": POST_STATUS_DRAFT,
        }
    )
    page_match = post_service.create_post(
        {
            "type": "page",
            "title": f"Hospitality page {marker}",
            "slug": f"hosp-page-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    post_service.assign_terms(title_match["id"], [news["id"]])

    return {
        "marker": marker,
        "title_match": title_match,
        "body_match": body_match,
        "excerpt_match": excerpt_match,
        "draft_match": draft_match,
        "page_match": page_match,
        "news_slug": f"news-{marker}",
    }


def _slugs(result):
    return [item["slug"] for item in result["items"]]


def _item_by_slug(result, slug):
    for item in result["items"]:
        if item["slug"] == slug:
            return item
    raise AssertionError(f"slug {slug!r} not in search results")


class TestMatching:
    def test_matches_title_excerpt_and_body(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        slugs = _slugs(result)
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        assert seeded["excerpt_match"]["slug"] in slugs

    def test_excludes_non_published(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        assert seeded["draft_match"]["slug"] not in _slugs(result)

    def test_blank_query_empty(self, db, seeded):
        result = _search_service(db).search("", page=1, per_page=50)
        assert result["items"] == []
        assert result["total"] == 0


class TestRanking:
    def test_title_match_outranks_body_match(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        slugs = _slugs(result)
        title_index = slugs.index(seeded["title_match"]["slug"])
        body_index = slugs.index(seeded["body_match"]["slug"])
        assert title_index < body_index


class TestFilters:
    def test_type_filter_narrows(self, db, seeded):
        result = _search_service(db).search(
            "hospitality", post_type="page", page=1, per_page=50
        )
        slugs = _slugs(result)
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] not in slugs

    def test_term_filter_narrows(self, db, seeded):
        result = _search_service(db).search(
            "hospitality",
            term_filter=("category", seeded["news_slug"]),
            page=1,
            per_page=50,
        )
        slugs = _slugs(result)
        assert seeded["title_match"]["slug"] in slugs
        # Only title_match is tagged with the news category.
        assert seeded["body_match"]["slug"] not in slugs


class TestPagination:
    def test_total_and_pages(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=2)
        assert result["per_page"] == 2
        assert result["total"] >= 3
        assert result["pages"] >= 2
        assert len(result["items"]) == 2


class TestIndexUsage:
    def test_gin_index_used_for_tsquery(self, db, seeded):
        # Force the planner to prefer the index for the seeded data set.
        db.session.execute(text("SET LOCAL enable_seqscan = off"))
        explain = db.session.execute(
            text(
                "EXPLAIN SELECT id FROM cms_post "
                "WHERE search_vector @@ websearch_to_tsquery('english', :q)"
            ),
            {"q": "hospitality"},
        ).fetchall()
        plan = "\n".join(row[0] for row in explain)
        assert "ix_cms_post_search_vector" in plan or "Bitmap Index Scan" in plan


class TestSearchRoute:
    def test_route_returns_ranked_published(self, client, db, seeded):
        resp = client.get("/api/v1/cms/search?q=hospitality&per_page=50")
        assert resp.status_code == 200
        body = resp.get_json()
        slugs = [item["slug"] for item in body["items"]]
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["draft_match"]["slug"] not in slugs

    def test_route_blank_query_empty(self, client, db, seeded):
        resp = client.get("/api/v1/cms/search?q=")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_route_term_filter_narrows(self, client, db, seeded):
        resp = client.get(
            "/api/v1/cms/search?q=hospitality"
            f"&term_type=category&term_slug={seeded['news_slug']}&per_page=50"
        )
        assert resp.status_code == 200
        slugs = [item["slug"] for item in resp.get_json()["items"]]
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] not in slugs


class TestCategoryCardEnrichment:
    """S12x — each search result item carries category-card fields:
    ``primary_category`` (first ``category`` term or null), ``excerpt_effective``
    (stored excerpt, else an HTML-stripped/truncated content fallback), and the
    already-serialized ``featured_image_url`` / ``og_image_url``.
    """

    def test_item_has_primary_category_when_categorized(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        item = _item_by_slug(result, seeded["title_match"]["slug"])
        assert item["primary_category"] == {
            "slug": seeded["news_slug"],
            "name": "News",
        }

    def test_item_primary_category_null_when_uncategorized(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        item = _item_by_slug(result, seeded["body_match"]["slug"])
        assert item["primary_category"] is None

    def test_excerpt_effective_uses_stored_excerpt(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        item = _item_by_slug(result, seeded["excerpt_match"]["slug"])
        assert item["excerpt_effective"] == seeded["excerpt_match"]["excerpt"]

    def test_excerpt_effective_falls_back_to_stripped_content(self, db, seeded):
        marker = seeded["marker"]
        long_html = (
            "<p>" + " ".join(f"hospitality word{index}" for index in range(40)) + "</p>"
        )
        long_post = _post_service(db).create_post(
            {
                "type": "post",
                "title": f"Long body {marker}",
                "slug": f"hosp-long-{marker}",
                "content_html": long_html,
                "status": POST_STATUS_PUBLISHED,
            }
        )
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        item = _item_by_slug(result, long_post["slug"])
        effective = item["excerpt_effective"]
        # Derived, not stored — the persisted excerpt stays empty.
        assert not (long_post["excerpt"] or "")
        # Fallback: HTML stripped, truncated on a word boundary, ellipsis added.
        assert "<" not in effective and ">" not in effective
        assert len(effective) <= 161
        assert effective.endswith("…")

    def test_excerpt_effective_decodes_html_entities(self, db, seeded):
        marker = seeded["marker"]
        entity_post = _post_service(db).create_post(
            {
                "type": "post",
                "title": f"Entities {marker}",
                "slug": f"hosp-entities-{marker}",
                "content_html": (
                    f"<p>hospitality tips &amp; tricks &lt;script&gt; {marker}</p>"
                ),
                "status": POST_STATUS_PUBLISHED,
            }
        )
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        effective = _item_by_slug(result, entity_post["slug"])["excerpt_effective"]
        assert "&" in effective and "<script>" in effective
        assert "&amp;" not in effective
        assert "&lt;" not in effective and "&gt;" not in effective

    def test_item_exposes_image_keys(self, db, seeded):
        result = _search_service(db).search("hospitality", page=1, per_page=50)
        item = _item_by_slug(result, seeded["title_match"]["slug"])
        assert "featured_image_url" in item
        assert "og_image_url" in item


class TestMultiTypeFilter:
    """Multi-type filtering: ``post_types`` (service/repo) and the ``types``
    comma-separated query param (route). Backward-compatible with the single
    ``post_type`` / ``type`` param; empty/None means all published types.
    """

    def _register_custom_type(self, key):
        post_type_registry.register_post_type(
            PostType(key=key, label=key.title(), routable=True, hierarchical=False)
        )

    def _publish(self, db, post_type, marker, slug_suffix):
        return _post_service(db).create_post(
            {
                "type": post_type,
                "title": f"Hospitality {slug_suffix} {marker}",
                "slug": f"hosp-{slug_suffix}-{marker}",
                "status": POST_STATUS_PUBLISHED,
            }
        )

    def test_service_post_types_returns_page_and_post_excludes_others(self, db, seeded):
        marker = seeded["marker"]
        self._register_custom_type("guide")
        guide = self._publish(db, "guide", marker, "guide")
        result = _search_service(db).search(
            "hospitality", post_types=["page", "post"], page=1, per_page=50
        )
        slugs = _slugs(result)
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        # The custom "guide" type is excluded — not named in post_types.
        assert guide["slug"] not in slugs
        # Drafts never surface.
        assert seeded["draft_match"]["slug"] not in slugs

    def test_service_single_element_post_types_equals_legacy_single(self, db, seeded):
        multi = _search_service(db).search(
            "hospitality", post_types=["page"], page=1, per_page=50
        )
        legacy = _search_service(db).search(
            "hospitality", post_type="page", page=1, per_page=50
        )
        assert set(_slugs(multi)) == set(_slugs(legacy))
        assert seeded["page_match"]["slug"] in _slugs(multi)
        assert seeded["title_match"]["slug"] not in _slugs(multi)

    def test_service_post_types_wins_over_post_type(self, db, seeded):
        # When both are given, post_types wins (page only, ignoring type=post).
        result = _search_service(db).search(
            "hospitality",
            post_type="post",
            post_types=["page"],
            page=1,
            per_page=50,
        )
        slugs = _slugs(result)
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] not in slugs

    def test_service_empty_post_types_means_all_published_types(self, db, seeded):
        result = _search_service(db).search(
            "hospitality", post_types=[], page=1, per_page=50
        )
        slugs = _slugs(result)
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["draft_match"]["slug"] not in slugs

    def test_service_custom_type_included_only_when_named(self, db, seeded):
        marker = seeded["marker"]
        self._register_custom_type("guide")
        guide = self._publish(db, "guide", marker, "guide")
        without = _search_service(db).search(
            "hospitality", post_types=["page", "post"], page=1, per_page=50
        )
        assert guide["slug"] not in _slugs(without)
        with_guide = _search_service(db).search(
            "hospitality", post_types=["guide"], page=1, per_page=50
        )
        assert guide["slug"] in _slugs(with_guide)
        assert seeded["page_match"]["slug"] not in _slugs(with_guide)

    def _route_slugs(self, client, query):
        resp = client.get(query)
        assert resp.status_code == 200
        return [item["slug"] for item in resp.get_json()["items"]]

    def test_route_types_page_and_post_returns_both_excludes_others(
        self, client, db, seeded
    ):
        marker = seeded["marker"]
        self._register_custom_type("guide")
        guide = self._publish(db, "guide", marker, "guide")
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&types=page,post&per_page=50"
        )
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        assert guide["slug"] not in slugs
        assert seeded["draft_match"]["slug"] not in slugs

    def test_route_types_single_equals_legacy_type(self, client, db, seeded):
        multi = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&types=page&per_page=50"
        )
        legacy = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&type=page&per_page=50"
        )
        assert set(multi) == set(legacy)
        assert seeded["page_match"]["slug"] in multi
        assert seeded["title_match"]["slug"] not in multi

    def test_route_absent_types_and_type_returns_all_published(
        self, client, db, seeded
    ):
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&per_page=50"
        )
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        assert seeded["draft_match"]["slug"] not in slugs

    def test_route_types_dedupes_and_ignores_blank_keys(self, client, db, seeded):
        # "page,,page, " → de-duped, blank-stripped → just ["page"].
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&types=page,,page,%20&per_page=50"
        )
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] not in slugs

    def test_route_custom_type_included_only_when_named(self, client, db, seeded):
        marker = seeded["marker"]
        self._register_custom_type("guide")
        guide = self._publish(db, "guide", marker, "guide")
        without = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&types=page,post&per_page=50"
        )
        assert guide["slug"] not in without
        with_guide = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&types=guide&per_page=50"
        )
        assert guide["slug"] in with_guide
        assert seeded["page_match"]["slug"] not in with_guide


class TestScopeToTypeMapping:
    """S121 regression guard — locks the widget ``scope`` → ``/cms/search``
    request mapping the two frontends rely on (no production code; the FTS
    backend already supports ``type`` filtering and forces ``published``):

      - ``scope=pages``  → ``?type=page`` → published pages only
      - ``scope=posts``  → ``?type=post`` → published posts only
      - ``scope=both``   → omit ``type``  → all published types (pages + posts)

    In every case a draft/unpublished post must never surface.
    """

    def _route_slugs(self, client, query):
        resp = client.get(query)
        assert resp.status_code == 200
        return [item["slug"] for item in resp.get_json()["items"]]

    def test_scope_pages_returns_only_pages(self, client, db, seeded):
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&type=page&per_page=50"
        )
        assert seeded["page_match"]["slug"] in slugs
        # A published post must be excluded when scope=pages (type=page).
        assert seeded["title_match"]["slug"] not in slugs
        assert seeded["body_match"]["slug"] not in slugs
        # Drafts never surface.
        assert seeded["draft_match"]["slug"] not in slugs

    def test_scope_posts_returns_only_posts(self, client, db, seeded):
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&type=post&per_page=50"
        )
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        # The published page must be excluded when scope=posts (type=post).
        assert seeded["page_match"]["slug"] not in slugs
        # Drafts never surface.
        assert seeded["draft_match"]["slug"] not in slugs

    def test_scope_both_omits_type_and_returns_pages_and_posts(
        self, client, db, seeded
    ):
        # scope=both maps to omitting the type param entirely (all published).
        slugs = self._route_slugs(
            client, "/api/v1/cms/search?q=hospitality&per_page=50"
        )
        assert seeded["page_match"]["slug"] in slugs
        assert seeded["title_match"]["slug"] in slugs
        assert seeded["body_match"]["slug"] in slugs
        # Drafts never surface, regardless of scope.
        assert seeded["draft_match"]["slug"] not in slugs
