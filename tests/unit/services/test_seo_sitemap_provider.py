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
    def __init__(self, seo_excluded=False):
        self.seo_excluded = seo_excluded


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
    """Test double exposing all published posts + per-post terms/siblings."""

    def __init__(self, posts):
        self._posts = posts

    def iter_candidate_posts(self):
        return list(self._posts)

    def terms_for(self, post):
        return post.terms

    def siblings_for(self, post):
        return []


def test_yields_visible_published_post():
    provider = CmsSitemapProvider(_Loader([_Post()]))
    entries = provider.sitemap_entries()
    assert len(entries) == 1
    assert entries[0].loc == "https://x/pricing"
    assert entries[0].lastmod == "2026-01-02T00:00:00+00:00"


def test_excludes_unpublished():
    provider = CmsSitemapProvider(_Loader([_Post(status=POST_STATUS_DRAFT)]))
    assert provider.sitemap_entries() == []


def test_excludes_noindex():
    provider = CmsSitemapProvider(_Loader([_Post(robots="noindex,follow")]))
    assert provider.sitemap_entries() == []


def test_excludes_seo_excluded_post():
    provider = CmsSitemapProvider(_Loader([_Post(seo_excluded=True)]))
    assert provider.sitemap_entries() == []


def test_excludes_post_with_excluded_term():
    post = _Post(terms=[_Term(seo_excluded=True)])
    provider = CmsSitemapProvider(_Loader([post]))
    assert provider.sitemap_entries() == []


def test_includes_hreflang_alternates():
    class _Sibling:
        def __init__(self, language, canonical_url):
            self.language = language
            self.canonical_url = canonical_url

    class _LoaderWithSiblings(_Loader):
        def siblings_for(self, post):
            return [_Sibling("de", "https://x/de/pricing")]

    provider = CmsSitemapProvider(_LoaderWithSiblings([_Post()]))
    entry = provider.sitemap_entries()[0]
    hreflangs = {alt["hreflang"] for alt in entry.alternates}
    assert "de" in hreflangs
    assert "en" in hreflangs
    assert "x-default" in hreflangs
