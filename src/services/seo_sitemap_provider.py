"""The cms sitemap provider (S47.1 §5).

Registered in ``CmsPlugin.on_enable``, it is a native registry-v2 provider
(``name="cms"``, ``count()``, ``page(offset, limit)`` — S154 P1). ``count()``
is the published-candidate count and ``page()`` reads one ``LIMIT/OFFSET``
window of candidates in primary-key order, so a chunk never loads every post.
The page then yields one entry per **search-visible** post (the §3.1
predicate) — a page can hold fewer than ``limit`` entries — with
``loc`` from the canonical URL, ``lastmod`` from ``updated_at``, and hreflang
alternates from the post's translation siblings. Archives/search URLs are NOT
emitted (D8) — only individual prerendered posts/pages.

``post_loader`` supplies the candidate posts and, per post, its terms and
translation siblings so the provider can apply the predicate + build hreflang
without importing the ORM here.

The ``seo_index_pages`` / ``seo_index_posts`` switches (S154 P2) are applied as
an ``excluded_post_types`` filter in the loader's SQL, for ``count()`` and
``page()`` alike, so the chunk plan and the chunks stay consistent.
"""
from typing import Callable, List, Optional, Tuple

from plugins.cms.src.services.seo_canonical import derive_canonical_url
from plugins.cms.src.services.seo_registry import SitemapEntry
from plugins.cms.src.services.seo_scope import (
    ScopeView,
    page_is_search_visible,
    resolve_private_path_prefixes,
)
from plugins.cms.src.services.seo_index_switches import resolve_seo_index_switches

CMS_SITEMAP_PROVIDER_NAME = "cms"

# The ``cms_post.type`` values the two content-type switches govern.
PAGE_POST_TYPE = "page"
POST_POST_TYPE = "post"


def excluded_post_types(config: dict) -> Tuple[str, ...]:
    """The post types switched off for indexing (``seo_index_pages/posts``)."""
    switches = resolve_seo_index_switches(config)
    excluded = []
    if not switches.pages:
        excluded.append(PAGE_POST_TYPE)
    if not switches.posts:
        excluded.append(POST_POST_TYPE)
    return tuple(excluded)


class CmsSitemapProvider:
    """The cms sitemap provider (registry v2) backed by published posts.

    ``loc`` prefers the post's stored ``canonical_url`` (the same absolute URL
    the meta-builder/canonical tag use) and falls back to
    ``<public_base_url>/<slug>`` when a post has no canonical URL — the SAME
    rule the RSS feed applies (DRY). A published post legitimately may have no
    canonical_url (the column is nullable), so the provider must never emit a
    ``SitemapEntry`` with ``loc=None``: that would crash core's agnostic
    ``/sitemap.xml`` renderer (``escape(None)``).

    ``public_base_url_provider`` is resolved lazily per call (mirroring the
    session resolution in ``seo_wiring``) so the provider stays config-agnostic
    and unit-testable with a simple double.
    """

    name = CMS_SITEMAP_PROVIDER_NAME

    def __init__(
        self,
        post_loader,
        public_base_url_provider: Optional[Callable[[], str]] = None,
        sitemap_config_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        self._post_loader = post_loader
        self._public_base_url_provider = public_base_url_provider or (lambda: "")
        self._sitemap_config_provider = sitemap_config_provider or (lambda: {})

    def count(self) -> int:
        config = self._sitemap_config_provider() or {}
        return self._post_loader.count_candidate_posts(
            excluded_post_types=excluded_post_types(config)
        )

    def page(self, offset: int, limit: int) -> List[SitemapEntry]:
        config = self._sitemap_config_provider() or {}
        private_path_prefixes = resolve_private_path_prefixes(config)
        entries: List[SitemapEntry] = []
        candidates = self._post_loader.iter_candidate_posts(
            offset=offset,
            limit=limit,
            excluded_post_types=excluded_post_types(config),
        )
        for post in candidates:
            terms = self._post_loader.terms_for(post)
            scope_view = ScopeView(post, terms)
            if not page_is_search_visible(scope_view, private_path_prefixes):
                continue
            if self._is_config_excluded(post, terms, config):
                continue
            entries.append(self._entry_for(post))
        return entries

    def _is_config_excluded(self, post, terms, config: dict) -> bool:
        """Apply the admin sitemap filters (S56) by slug / terms.

        The by-type filter (``sitemap_include_pages``, now folded into
        ``seo_index_pages``) runs in SQL via ``excluded_post_types``.
        """
        if post.slug in set(config.get("sitemap_excluded_slugs") or []):
            return True
        term_slugs = {getattr(term, "slug", None) for term in (terms or [])}
        include_terms = config.get("sitemap_include_terms") or []
        if include_terms and term_slugs.isdisjoint(set(include_terms)):
            return True
        if not term_slugs.isdisjoint(set(config.get("sitemap_exclude_terms") or [])):
            return True
        return False

    def _public_base_url(self) -> str:
        return (self._public_base_url_provider() or "").rstrip("/")

    def _loc_for(self, canonical_url: Optional[str], slug: Optional[str]) -> str:
        """Absolute URL for a post: stored canonical, else base + slug.

        Delegates to the shared ``derive_canonical_url`` rule (DRY) so the
        sitemap ``loc`` and the prerender canonical/JSON-LD ``url`` agree.
        """
        return derive_canonical_url(canonical_url, slug, self._public_base_url())

    def _entry_for(self, post) -> SitemapEntry:
        siblings = self._post_loader.siblings_for(post)
        loc = self._loc_for(post.canonical_url, post.slug)
        alternates = self._alternates(post, loc, siblings)
        return SitemapEntry(
            loc=loc,
            lastmod=(post.updated_at.isoformat() if post.updated_at else None),
            changefreq="weekly",
            priority="0.5",
            alternates=alternates,
        )

    def _alternates(self, post, loc, siblings) -> List[dict]:
        if not siblings:
            return []
        alternates = [{"hreflang": post.language, "href": loc}]
        for sibling in siblings:
            sibling_loc = self._loc_for(
                sibling.canonical_url, getattr(sibling, "slug", None)
            )
            alternates.append({"hreflang": sibling.language, "href": sibling_loc})
        alternates.append({"hreflang": "x-default", "href": loc})
        return alternates
