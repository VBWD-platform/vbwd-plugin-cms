"""S154 P2 — the ``cms-categories`` / ``cms-tags`` term-archive sitemap providers.

Each provider lists the public archive URL of a term family (``/category/<slug>``
and ``/tag/<slug>``, via the single ``term_archive_path`` map) and is active only
when its switch (``seo_index_categories`` / ``seo_index_tags``) is on. Off ⇒
``count() == 0`` and an empty page, so the sitemap index lists no chunk for it.
"""
from datetime import datetime, timezone

from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, TAG_TERM_TYPE
from plugins.cms.src.services.seo_registry import ISitemapProvider
from plugins.cms.src.services.seo_term_archive_loader import TermArchiveRow
from plugins.cms.src.services.seo_term_archive_sitemap_provider import (
    CMS_CATEGORIES_SITEMAP_PROVIDER_NAME,
    CMS_TAGS_SITEMAP_PROVIDER_NAME,
    build_category_archive_provider,
    build_tag_archive_provider,
)

_UPDATED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class _ArchiveSource:
    """Test double honouring the source contract (exclusion narrows both calls)."""

    def __init__(self, slugs):
        self._rows = [TermArchiveRow(slug=slug, lastmod=_UPDATED_AT) for slug in slugs]
        self.page_requests = []

    def _visible(self, excluded_slugs):
        return [row for row in self._rows if row.slug not in set(excluded_slugs)]

    def count_archives(self, excluded_slugs=()):
        return len(self._visible(excluded_slugs))

    def archive_page(self, offset, limit, excluded_slugs=()):
        self.page_requests.append((offset, limit))
        return self._visible(excluded_slugs)[offset : offset + limit]


def _category_provider(slugs, config, base_url="https://site.test"):
    return build_category_archive_provider(
        _ArchiveSource(slugs),
        public_base_url_provider=lambda: base_url,
        sitemap_config_provider=lambda: config,
    )


def _tag_provider(slugs, config):
    return build_tag_archive_provider(
        _ArchiveSource(slugs),
        public_base_url_provider=lambda: "https://site.test/",
        sitemap_config_provider=lambda: config,
    )


def test_providers_have_stable_url_safe_names_and_the_v2_shape():
    category_provider = _category_provider([], {})
    tag_provider = _tag_provider([], {})
    assert (
        category_provider.name
        == CMS_CATEGORIES_SITEMAP_PROVIDER_NAME
        == "cms-categories"
    )
    assert tag_provider.name == CMS_TAGS_SITEMAP_PROVIDER_NAME == "cms-tags"
    assert isinstance(category_provider, ISitemapProvider)
    assert isinstance(tag_provider, ISitemapProvider)


def test_off_by_default_count_is_zero_and_page_is_empty():
    for provider in (_category_provider(["news"], {}), _tag_provider(["vue"], {})):
        assert provider.count() == 0
        assert list(provider.page(0, 10)) == []


def test_categories_on_lists_the_category_archive_urls():
    provider = _category_provider(["news", "guides"], {"seo_index_categories": True})
    entries = list(provider.page(0, provider.count()))
    assert [entry.loc for entry in entries] == [
        "https://site.test/category/news",
        "https://site.test/category/guides",
    ]
    assert entries[0].lastmod == _UPDATED_AT.isoformat()


def test_tags_on_lists_the_tag_archive_urls():
    provider = _tag_provider(["vue"], {"seo_index_tags": True})
    assert provider.count() == 1
    assert [entry.loc for entry in provider.page(0, 1)] == ["https://site.test/tag/vue"]


def test_without_a_base_url_the_loc_is_root_relative():
    provider = _category_provider(["news"], {"seo_index_categories": True}, "")
    assert [entry.loc for entry in provider.page(0, 1)] == ["/category/news"]


def test_switches_are_independent():
    config = {"seo_index_categories": True}
    assert _category_provider(["news"], config).count() == 1
    assert _tag_provider(["vue"], config).count() == 0


def test_sitemap_exclude_terms_drop_the_archive_from_count_and_page():
    config = {"seo_index_categories": True, "sitemap_exclude_terms": ["private"]}
    provider = _category_provider(["news", "private", "guides"], config)
    assert provider.count() == 2
    assert [entry.loc for entry in provider.page(0, 5)] == [
        "https://site.test/category/news",
        "https://site.test/category/guides",
    ]


def test_paging_is_consistent_with_count():
    slugs = [f"term-{index}" for index in range(5)]
    provider = _category_provider(slugs, {"seo_index_categories": True})
    paged_locs = [
        entry.loc
        for offset in range(0, provider.count(), 2)
        for entry in provider.page(offset, 2)
    ]
    assert paged_locs == [f"https://site.test/category/{slug}" for slug in slugs]


def test_term_types_map_to_their_archive_prefixes():
    assert _category_provider([], {}).term_type == CATEGORY_TERM_TYPE
    assert _tag_provider([], {}).term_type == TAG_TERM_TYPE
