"""S47.1 — the single search-visibility predicate (truth table).

``page_is_search_visible(post)`` is the ONE rule shared by the meta-builder,
the prerender writer, and the sitemap provider. No consumer re-implements it.
"""
from dataclasses import dataclass, field
from typing import List

from plugins.cms.src.services.seo_scope import (
    DEFAULT_PRIVATE_PATH_PREFIXES,
    page_is_search_visible,
    path_is_private,
    resolve_private_path_prefixes,
)
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


# ── private-path rule: /dashboard, /tuktuk, /pay are never indexed ────────────


@dataclass
class _SluggedPost(_Post):
    slug: str = "pricing"


def test_default_private_prefixes_cover_the_private_areas():
    assert set(DEFAULT_PRIVATE_PATH_PREFIXES) == {
        "/dashboard",
        "/tuktuk",
        "/pay",
    }


def test_catalogue_base_is_public_by_default():
    """D9: the ghrm catalogue base (admin-configurable) is never hardcoded private."""
    assert path_is_private("/software", DEFAULT_PRIVATE_PATH_PREFIXES) is False
    assert path_is_private("software/mobile", DEFAULT_PRIVATE_PATH_PREFIXES) is False


def test_path_under_private_prefix_is_private():
    prefixes = DEFAULT_PRIVATE_PATH_PREFIXES
    assert path_is_private("/pay", prefixes) is True
    assert path_is_private("pay", prefixes) is True
    assert path_is_private("pay/invoice", prefixes) is True
    assert path_is_private("/pay/checkout?step=2", prefixes) is True
    assert path_is_private("/dashboard/", prefixes) is True
    assert path_is_private("/TukTuk/reports", prefixes) is True


def test_private_prefix_match_is_segment_aware():
    prefixes = DEFAULT_PRIVATE_PATH_PREFIXES
    assert path_is_private("/payx", prefixes) is False
    assert path_is_private("/payments", prefixes) is False
    assert path_is_private("payments-guide", prefixes) is False
    assert path_is_private("/blog/pay", prefixes) is False
    assert path_is_private("/", prefixes) is False


def test_blank_prefix_never_makes_everything_private():
    assert path_is_private("/pricing", ["", "/", "  "]) is False


def test_resolve_prefixes_defaults_when_key_absent():
    assert resolve_private_path_prefixes({}) == DEFAULT_PRIVATE_PATH_PREFIXES


def test_resolve_prefixes_honours_saved_override():
    config = {"seo_private_path_prefixes": []}
    assert resolve_private_path_prefixes(config) == ()
    config = {"seo_private_path_prefixes": ["members/", "/vip"]}
    assert resolve_private_path_prefixes(config) == ("/members", "/vip")


def test_resolve_prefixes_accepts_comma_separated_string():
    config = {"seo_private_path_prefixes": "/pay, members ,"}
    assert resolve_private_path_prefixes(config) == ("/pay", "/members")


def test_post_under_private_path_is_not_search_visible():
    prefixes = DEFAULT_PRIVATE_PATH_PREFIXES
    assert page_is_search_visible(_SluggedPost(slug="pay"), prefixes) is False
    assert page_is_search_visible(_SluggedPost(slug="pay/invoice"), prefixes) is False
    assert page_is_search_visible(_SluggedPost(slug="payx"), prefixes) is True
    assert page_is_search_visible(_SluggedPost(slug="software"), prefixes) is True


def test_no_private_prefixes_keeps_path_rule_off():
    assert page_is_search_visible(_SluggedPost(slug="pay")) is True
