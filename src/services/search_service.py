"""SearchService — full-text search over published posts (S47.4).

Thin orchestration over SearchRepository: enforce the published-only filter,
short-circuit blank queries to an empty result (never "all posts"), forward the
optional ``type`` and term filters, and serialize results into the SAME summary
page shape PostService emits, so the Search-results widget reuses PostList (DRY).
"""
from typing import Any, Dict, Optional, Tuple

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


class SearchService:
    """Search published posts via Postgres FTS."""

    def __init__(self, repo) -> None:
        self._repo = repo

    def search(
        self,
        query: Optional[str],
        *,
        post_type: Optional[str] = None,
        term_filter: Optional[Tuple[str, str]] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        if not query or not query.strip():
            return self._empty_page(page, per_page)

        term_type, term_slug = term_filter if term_filter else (None, None)
        result = self._repo.search(
            query=query.strip(),
            status=POST_STATUS_PUBLISHED,
            post_type=post_type,
            term_type=term_type,
            term_slug=term_slug,
            page=page,
            per_page=per_page,
        )
        return self._serialize_page(result, page, per_page)

    def _serialize_page(
        self, result: Dict[str, Any], page: int, per_page: int
    ) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in result.get("items", [])],
            "total": result.get("total", 0),
            "page": result.get("page", page),
            "per_page": result.get("per_page", per_page),
            "pages": result.get("pages", 1),
        }

    def _empty_page(self, page: int, per_page: int) -> Dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "pages": 1,
        }
