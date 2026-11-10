"""The ``cms-categories`` / ``cms-tags`` sitemap providers (S154 P2, registry v2).

Each lists the public archive URL of one term family — ``/category/<slug>`` or
``/tag/<slug>``, built by the single ``term_archive_path`` map the site and the
terms API use — and is active only while its fe-admin switch is on
(``seo_index_categories`` / ``seo_index_tags``, both default off). Switched off,
``count()`` is 0, so ``/sitemap.xml`` lists no chunk for it.

Config is read lazily per call (like ``CmsSitemapProvider``), so a saved switch
takes effect on the next sitemap request without re-enabling the plugin. Term
slugs in ``sitemap_exclude_terms`` are left out (in SQL, for count and page
alike); private paths are filtered centrally by the chunker (D1).
"""
from typing import Callable, List, Optional, Protocol, Sequence

from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, TAG_TERM_TYPE
from plugins.cms.src.services.seo_canonical import derive_canonical_url
from plugins.cms.src.services.seo_index_switches import (
    SeoIndexSwitches,
    resolve_seo_index_switches,
)
from plugins.cms.src.services.seo_registry import SitemapEntry
from plugins.cms.src.services.seo_term_archive_loader import TermArchiveRow
from plugins.cms.src.services.term_permalink import term_archive_path

CMS_CATEGORIES_SITEMAP_PROVIDER_NAME = "cms-categories"
CMS_TAGS_SITEMAP_PROVIDER_NAME = "cms-tags"

EXCLUDED_TERMS_CONFIG_KEY = "sitemap_exclude_terms"


class ITermArchiveSource(Protocol):
    """A DB-paged source of term archives (see ``seo_term_archive_loader``)."""

    def count_archives(self, excluded_slugs: Sequence[str] = ()) -> int:
        ...

    def archive_page(
        self, offset: int, limit: int, excluded_slugs: Sequence[str] = ()
    ) -> List[TermArchiveRow]:
        ...


class CmsTermArchiveSitemapProvider:
    """One term family's archive URLs, gated by its indexable switch."""

    def __init__(
        self,
        name: str,
        term_type: str,
        archive_source: ITermArchiveSource,
        index_switch: Callable[[SeoIndexSwitches], bool],
        public_base_url_provider: Optional[Callable[[], str]] = None,
        sitemap_config_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        self.name = name
        self.term_type = term_type
        self._archive_source = archive_source
        self._index_switch = index_switch
        self._public_base_url_provider = public_base_url_provider or (lambda: "")
        self._sitemap_config_provider = sitemap_config_provider or (lambda: {})

    def count(self) -> int:
        config = self._sitemap_config_provider() or {}
        if not self._is_enabled(config):
            return 0
        return self._archive_source.count_archives(self._excluded_slugs(config))

    def page(self, offset: int, limit: int) -> List[SitemapEntry]:
        config = self._sitemap_config_provider() or {}
        if not self._is_enabled(config):
            return []
        rows = self._archive_source.archive_page(
            offset, limit, self._excluded_slugs(config)
        )
        public_base_url = self._public_base_url_provider() or ""
        return [self._entry_for(row, public_base_url) for row in rows]

    def _is_enabled(self, config: dict) -> bool:
        return self._index_switch(resolve_seo_index_switches(config))

    @staticmethod
    def _excluded_slugs(config: dict) -> List[str]:
        return list(config.get(EXCLUDED_TERMS_CONFIG_KEY) or [])

    def _entry_for(self, row: TermArchiveRow, public_base_url: str) -> SitemapEntry:
        archive_path = term_archive_path(self.term_type, row.slug)
        return SitemapEntry(
            loc=derive_canonical_url(None, archive_path, public_base_url),
            lastmod=row.lastmod.isoformat() if row.lastmod else None,
            changefreq="weekly",
        )


def build_category_archive_provider(
    archive_source: ITermArchiveSource,
    public_base_url_provider: Optional[Callable[[], str]] = None,
    sitemap_config_provider: Optional[Callable[[], dict]] = None,
) -> CmsTermArchiveSitemapProvider:
    """The ``cms-categories`` provider (``seo_index_categories``)."""
    return CmsTermArchiveSitemapProvider(
        CMS_CATEGORIES_SITEMAP_PROVIDER_NAME,
        CATEGORY_TERM_TYPE,
        archive_source,
        lambda switches: switches.categories,
        public_base_url_provider,
        sitemap_config_provider,
    )


def build_tag_archive_provider(
    archive_source: ITermArchiveSource,
    public_base_url_provider: Optional[Callable[[], str]] = None,
    sitemap_config_provider: Optional[Callable[[], dict]] = None,
) -> CmsTermArchiveSitemapProvider:
    """The ``cms-tags`` provider (``seo_index_tags``)."""
    return CmsTermArchiveSitemapProvider(
        CMS_TAGS_SITEMAP_PROVIDER_NAME,
        TAG_TERM_TYPE,
        archive_source,
        lambda switches: switches.tags,
        public_base_url_provider,
        sitemap_config_provider,
    )
