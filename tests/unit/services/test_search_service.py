"""Unit tests for SearchService (S47.4) — MagicMock repo, no DB.

The FTS SQL lives in SearchRepository (exercised against real PG in the
integration suite). These unit tests pin the service contract:
  - blank/empty query → empty result WITHOUT touching the repo (no all-posts);
  - non-blank query delegates to the repo with the published-only filter plus
    optional ``type`` and term filter, and forwards pagination;
  - the service returns the SAME summary page shape PostService produces (DRY).
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

from plugins.cms.src.models.cms_post import CmsPost, POST_STATUS_PUBLISHED
from plugins.cms.src.services.search_service import SearchService


def _post(slug="hello", title="Hello", status=POST_STATUS_PUBLISHED):
    post = CmsPost()
    post.id = uuid4()
    post.type = "post"
    post.slug = slug
    post.title = title
    post.excerpt = None
    post.content_json = {}
    post.content_html = None
    post.status = status
    post.parent_id = None
    post.published_at = None
    post.language = "en"
    post.sort_order = 0
    post.created_at = post.updated_at = datetime.datetime.utcnow()
    return post


def _make_service(found=None, total=None):
    repo = MagicMock()
    items = found if found is not None else []
    repo.search.return_value = {
        "items": items,
        "total": total if total is not None else len(items),
        "page": 1,
        "per_page": 20,
        "pages": 1,
    }
    return SearchService(repo=repo), repo


class TestBlankQuery:
    def test_blank_query_returns_empty_without_repo_call(self):
        service, repo = _make_service(found=[_post()])
        result = service.search("", page=1, per_page=20)
        assert result["items"] == []
        assert result["total"] == 0
        repo.search.assert_not_called()

    def test_whitespace_query_returns_empty_without_repo_call(self):
        service, repo = _make_service(found=[_post()])
        result = service.search("   ", page=1, per_page=20)
        assert result["items"] == []
        assert result["total"] == 0
        repo.search.assert_not_called()

    def test_none_query_returns_empty(self):
        service, repo = _make_service()
        result = service.search(None, page=1, per_page=20)
        assert result["items"] == []
        repo.search.assert_not_called()


class TestDelegation:
    def test_query_delegates_published_only(self):
        service, repo = _make_service(found=[_post(slug="match")])
        service.search("hello", page=1, per_page=20)
        kwargs = repo.search.call_args.kwargs
        assert kwargs["query"] == "hello"
        assert kwargs["status"] == POST_STATUS_PUBLISHED

    def test_type_and_term_filter_forwarded(self):
        service, repo = _make_service()
        service.search(
            "hello",
            post_type="post",
            term_filter=("category", "news"),
            page=2,
            per_page=5,
        )
        kwargs = repo.search.call_args.kwargs
        assert kwargs["post_type"] == "post"
        assert kwargs["term_type"] == "category"
        assert kwargs["term_slug"] == "news"
        assert kwargs["page"] == 2
        assert kwargs["per_page"] == 5

    def test_no_term_filter_passes_none(self):
        service, repo = _make_service()
        service.search("hello", page=1, per_page=20)
        kwargs = repo.search.call_args.kwargs
        assert kwargs["term_type"] is None
        assert kwargs["term_slug"] is None


class TestSummaryShape:
    def test_returns_serialized_summary_page(self):
        post = _post(slug="hospitality", title="Hospitality")
        service, _ = _make_service(found=[post], total=1)
        result = service.search("hospitality", page=1, per_page=20)
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["per_page"] == 20
        assert result["pages"] == 1
        item = result["items"][0]
        # Same dict shape PostService._serialize_page emits (DRY).
        assert item["slug"] == "hospitality"
        assert item["title"] == "Hospitality"
        assert item["type"] == "post"

    def test_empty_repo_result_yields_empty_items(self):
        service, _ = _make_service(found=[], total=0)
        result = service.search("nomatch", page=1, per_page=20)
        assert result["items"] == []
        assert result["total"] == 0
