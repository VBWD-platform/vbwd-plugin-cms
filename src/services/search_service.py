"""SearchService — full-text search over published posts (S47.4).

Thin orchestration over SearchRepository: enforce the published-only filter,
short-circuit blank queries to an empty result (never "all posts"), forward the
optional ``type`` and term filters, and serialize results into the SAME summary
page shape PostService emits, so the Search-results widget reuses PostList (DRY).
"""
import html
import re
from typing import Any, Dict, Optional, Tuple

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


# Character budget for the derived excerpt fallback (WordPress-style card teaser).
# The stripped body is cut on a word boundary within this budget, then a single
# ellipsis character is appended — so the total never exceeds budget + 1.
EXCERPT_FALLBACK_MAX_CHARS = 160
EXCERPT_ELLIPSIS = "…"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(content_html: Optional[str]) -> str:
    """Strip tags, decode HTML entities, then collapse whitespace.

    Order matters: remove tags first, then ``html.unescape`` so entities such as
    ``&amp;`` / ``&lt;script&gt;`` / ``&rsaquo;`` become real characters, then
    collapse runs of whitespace to a single space.
    """
    without_tags = _HTML_TAG_RE.sub(" ", content_html or "")
    unescaped = html.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


def compute_excerpt_effective(
    excerpt: Optional[str], content_html: Optional[str]
) -> str:
    """Return the stored excerpt if non-empty, else a stripped/truncated body.

    Derived (never mutates the stored ``excerpt``). The fallback strips HTML,
    collapses whitespace, truncates on a word boundary within
    ``EXCERPT_FALLBACK_MAX_CHARS`` and appends a single ellipsis when it cut.
    """
    if excerpt and excerpt.strip():
        return excerpt
    stripped = _strip_html(content_html)
    if len(stripped) <= EXCERPT_FALLBACK_MAX_CHARS:
        return stripped
    cut = stripped[:EXCERPT_FALLBACK_MAX_CHARS]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip() + EXCERPT_ELLIPSIS


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
        posts = result.get("items", [])
        # One grouped query for the whole page's primary categories (no N+1).
        primary_by_post = self._repo.primary_categories_for_posts(
            [post.id for post in posts]
        )
        items = []
        for post in posts:
            serialized = post.to_dict()
            serialized["primary_category"] = primary_by_post.get(post.id)
            serialized["excerpt_effective"] = compute_excerpt_effective(
                post.excerpt, post.content_html
            )
            items.append(serialized)
        return {
            "items": items,
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
