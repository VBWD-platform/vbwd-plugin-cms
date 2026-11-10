"""S47.1 — the cms sitemap provider (search-visible posts only).

Yields a ``SitemapEntry`` per search-visible post (loc from canonical/(type,
slug), lastmod from updated_at, hreflang alternates), excluding non-visible
posts via the §3.1 predicate. Archives/search URLs are NOT emitted (D8).
"""
from datetime import datetime, timezone

from plugins.cms.src.services.seo_sitemap_provider import CmsSitemapProvider
from plugins.cms.src.models.cms_post import (
    POST_STATUS_PUBLISHED,
    POST_STATUS_DRAFT,
)


class _Term:
    def __init__(self, seo_excluded=False, slug="news"):
        self.seo_excluded = seo_excluded
        self.slug = slug


class _Post:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "p1")
        self.type = kwargs.get("type", "page")
        self.slug = kwargs.get("slug", "pricing")
        self.status = kwargs.get("status", POST_STATUS_PUBLISHED)
        self.robots = kwargs.get("robots", "index,follow")
        self.seo_excluded = kwargs.get("seo_excluded", False)
        self.canonical_url = kwargs.get("canonical_url", "https://x/pricing")
        self.updated_at = kwargs.get(
            "updated_at", datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
        self.language = kwargs.get("language", "en")
        self.translation_group_id = kwargs.get("translation_group_id", None)
        self.terms = kwargs.get("terms", [])


class _Loader:
    """Test double exposing all published posts + per-post terms/siblings.

    Honours the real loader's contract: ``excluded_post_types`` narrows BOTH
    the count and the paged window (the SQL ``type NOT IN`` filter).
    """

    def __init__(self, posts):
        self._posts = posts

    def _candidates(self, excluded_post_types):
        return [post for post in self._posts if post.type not in excluded_post_types]

    def count_candidate_posts(self, excluded_post_types=()):
        return len(self._candidates(excluded_post_types))

    def iter_candidate_posts(self, offset=0, limit=None, excluded_post_types=()):
        stop = None if limit is None else offset + limit
        return list(self._candidates(excluded_post_types)[offset:stop])

    def terms_for(self, post):
        return post.terms

    def siblings_for(self, post):
        return []


def _all_entries(provider):
    """Every entry the v2 provider yields, walked as ONE page of ``count()``."""
    return list(provider.page(0, provider.count()))


def test_yields_visible_published_post():
    provider = CmsSitemapProvider(_Loader([_Post()]))
    entries = _all_entries(provider)
    assert len(entries) == 1
    assert entries[0].loc == "https://x/pricing"
    assert entries[0].lastmod == "2026-01-02T00:00:00+00:00"


def test_excludes_unpublished():
    provider = CmsSitemapProvider(_Loader([_Post(status=POST_STATUS_DRAFT)]))
    assert _all_entries(provider) == []


def test_excludes_noindex():
    provider = CmsSitemapProvider(_Loader([_Post(robots="noindex,follow")]))
    assert _all_entries(provider) == []


def test_excludes_seo_excluded_post():
    provider = CmsSitemapProvider(_Loader([_Post(seo_excluded=True)]))
    assert _all_entries(provider) == []


def test_excludes_post_with_excluded_term():
    post = _Post(terms=[_Term(seo_excluded=True)])
    provider = CmsSitemapProvider(_Loader([post]))
    assert _all_entries(provider) == []


# ── S56.0: admin sitemap-config filtering ────────────────────────────────────


def _provider(posts, config):
    return CmsSitemapProvider(_Loader(posts), sitemap_config_provider=lambda: config)


def test_excludes_pages_when_include_pages_false():
    post = _Post(type="page")
    assert _all_entries(_provider([post], {"sitemap_include_pages": False})) == []


def test_keeps_non_page_when_include_pages_false():
    post = _Post(type="post")
    entries = _all_entries(_provider([post], {"sitemap_include_pages": False}))
    assert len(entries) == 1


def test_excludes_post_by_excluded_slug():
    post = _Post(slug="hidden")
    config = {"sitemap_excluded_slugs": ["hidden"]}
    assert _all_entries(_provider([post], config)) == []


def test_include_terms_restricts_to_matching_posts():
    matching = _Post(slug="a", terms=[_Term(slug="featured")])
    other = _Post(slug="b", terms=[_Term(slug="news")])
    config = {"sitemap_include_terms": ["featured"]}
    entries = _all_entries(_provider([matching, other], config))
    locs = {entry.loc for entry in entries}
    assert "https://x/pricing" in locs or len(entries) == 1
    assert len(entries) == 1


def test_exclude_terms_drops_matching_posts():
    post = _Post(terms=[_Term(slug="private")])
    config = {"sitemap_exclude_terms": ["private"]}
    assert _all_entries(_provider([post], config)) == []


def test_empty_config_behaves_like_no_filter():
    post = _Post(type="page")
    assert len(_all_entries(_provider([post], {}))) == 1


def test_includes_hreflang_alternates():
    class _Sibling:
        def __init__(self, language, canonical_url):
            self.language = language
            self.canonical_url = canonical_url

    class _LoaderWithSiblings(_Loader):
        def siblings_for(self, post):
            return [_Sibling("de", "https://x/de/pricing")]

    provider = CmsSitemapProvider(_LoaderWithSiblings([_Post()]))
    entry = _all_entries(provider)[0]
    hreflangs = {alt["hreflang"] for alt in entry.alternates}
    assert "de" in hreflangs
    assert "en" in hreflangs
    assert "x-default" in hreflangs


# ── private paths (/dashboard, /tuktuk, /pay) are never advertised ────────────


def _slugged_posts(*slugs):
    return [
        _Post(id=slug, slug=slug, canonical_url=f"https://x/{slug}") for slug in slugs
    ]


def test_private_path_posts_are_excluded_by_default():
    posts = _slugged_posts("dashboard", "dashboard/orders", "pay", "dashboardx")
    posts += _slugged_posts("payments-guide", "software")
    entries = _all_entries(CmsSitemapProvider(_Loader(posts)))
    assert sorted(entry.loc for entry in entries) == [
        "https://x/dashboardx",
        "https://x/payments-guide",
        "https://x/software",
    ]


def test_private_path_rule_is_config_driven():
    posts = _slugged_posts("pay", "pay/invoice")
    provider = _provider(posts, {"seo_private_path_prefixes": []})
    assert len(_all_entries(provider)) == 2


# ── S154 P1: native registry-v2 contract (name / count / page) ────────────────


class _RecordingLoader(_Loader):
    def __init__(self, posts):
        super().__init__(posts)
        self.page_requests = []

    def iter_candidate_posts(self, offset=0, limit=None, excluded_post_types=()):
        self.page_requests.append((offset, limit))
        return super().iter_candidate_posts(offset, limit, excluded_post_types)


def test_provider_is_named_cms():
    assert CmsSitemapProvider(_Loader([])).name == "cms"


def test_count_is_the_candidate_count_from_the_loader():
    posts = _slugged_posts("a", "b", "c")
    assert CmsSitemapProvider(_Loader(posts)).count() == 3


def test_page_reads_only_the_requested_window():
    loader = _RecordingLoader(_slugged_posts("a", "b", "c"))
    entries = list(CmsSitemapProvider(loader).page(1, 1))
    assert loader.page_requests == [(1, 1)]
    assert [entry.loc for entry in entries] == ["https://x/b"]


def test_paging_covers_the_same_urls_as_one_full_page():
    posts = _slugged_posts("a", "b", "dashboard", "c", "d")
    provider = CmsSitemapProvider(_Loader(posts))
    paged_locs = [
        entry.loc
        for offset in range(0, provider.count(), 2)
        for entry in provider.page(offset, 2)
    ]
    assert paged_locs == [entry.loc for entry in _all_entries(provider)]
    assert paged_locs == ["https://x/a", "https://x/b", "https://x/c", "https://x/d"]


# ── S154 P2: the seo_index_pages / seo_index_posts switches ──────────────────


def _typed_posts():
    return [
        _Post(id="p1", type="page", slug="about", canonical_url="https://x/about"),
        _Post(id="p2", type="post", slug="news", canonical_url="https://x/news"),
        _Post(id="p3", type="page", slug="team", canonical_url="https://x/team"),
    ]


def test_index_pages_off_drops_pages_from_count_and_page():
    provider = _provider(_typed_posts(), {"seo_index_pages": False})
    assert provider.count() == 1
    assert [entry.loc for entry in _all_entries(provider)] == ["https://x/news"]


def test_index_posts_off_drops_posts_from_count_and_page():
    provider = _provider(_typed_posts(), {"seo_index_posts": False})
    assert provider.count() == 2
    assert [entry.loc for entry in _all_entries(provider)] == [
        "https://x/about",
        "https://x/team",
    ]


def test_index_pages_saved_on_wins_over_legacy_include_pages_off():
    config = {"seo_index_pages": True, "sitemap_include_pages": False}
    provider = _provider(_typed_posts(), config)
    assert provider.count() == 3


def test_both_switches_off_leave_an_empty_provider():
    config = {"seo_index_pages": False, "seo_index_posts": False}
    provider = _provider(_typed_posts(), config)
    assert provider.count() == 0
    assert list(provider.page(0, 10)) == []


def test_switch_filter_keeps_paging_consistent_with_count():
    provider = _provider(_typed_posts(), {"seo_index_posts": False})
    paged_locs = [
        entry.loc
        for offset in range(0, provider.count(), 1)
        for entry in provider.page(offset, 1)
    ]
    assert paged_locs == ["https://x/about", "https://x/team"]
