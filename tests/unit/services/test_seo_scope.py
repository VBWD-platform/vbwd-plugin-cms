"""S47.1 — the single search-visibility predicate (truth table).

``page_is_search_visible(post)`` is the ONE rule shared by the meta-builder,
the prerender writer, and the sitemap provider. No consumer re-implements it.
"""
from dataclasses import dataclass, field
from typing import List

from plugins.cms.src.services.seo_scope import page_is_search_visible
from plugins.cms.src.models.cms_post import (
    POST_STATUS_PUBLISHED,
    POST_STATUS_DRAFT,
    POST_STATUS_PENDING,
    POST_STATUS_SCHEDULED,
    POST_STATUS_PRIVATE,
    POST_STATUS_TRASH,
)


@dataclass
class _Term:
    seo_excluded: bool = False


@dataclass
class _Post:
    status: str = POST_STATUS_PUBLISHED
    seo_excluded: bool = False
    robots: str = "index,follow"
    terms: List[_Term] = field(default_factory=list)


def test_published_clean_is_visible():
    assert page_is_search_visible(_Post()) is True


def test_seo_excluded_post_not_visible():
    assert page_is_search_visible(_Post(seo_excluded=True)) is False


def test_any_excluded_term_makes_not_visible():
    post = _Post(terms=[_Term(seo_excluded=False), _Term(seo_excluded=True)])
    assert page_is_search_visible(post) is False


def test_clean_terms_stay_visible():
    post = _Post(terms=[_Term(seo_excluded=False), _Term(seo_excluded=False)])
    assert page_is_search_visible(post) is True


def test_noindex_robots_not_visible():
    assert page_is_search_visible(_Post(robots="noindex,nofollow")) is False
    assert page_is_search_visible(_Post(robots="noindex,follow")) is False


def test_non_published_statuses_not_visible():
    for status in (
        POST_STATUS_DRAFT,
        POST_STATUS_PENDING,
        POST_STATUS_SCHEDULED,
        POST_STATUS_PRIVATE,
        POST_STATUS_TRASH,
    ):
        assert page_is_search_visible(_Post(status=status)) is False
