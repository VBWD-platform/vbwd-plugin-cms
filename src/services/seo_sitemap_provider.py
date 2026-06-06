"""The cms sitemap provider (S47.1 §5).

Registered in ``CmsPlugin.on_enable``, it satisfies the core
``ISeoSitemapProvider`` duck-type: ``sitemap_entries() -> [SitemapEntry]``. It
yields one entry per **search-visible** post (the §3.1 predicate), with
``loc`` from the canonical URL, ``lastmod`` from ``updated_at``, and hreflang
alternates from the post's translation siblings. Archives/search URLs are NOT
emitted (D8) — only individual prerendered posts/pages.

``post_loader`` supplies the candidate posts and, per post, its terms and
translation siblings so the provider can apply the predicate + build hreflang
without importing the ORM here.
"""
from typing import Callable, List, Optional

from plugins.cms.src.services.seo_registry import SitemapEntry
from plugins.cms.src.services.seo_scope import page_is_search_visible


class CmsSitemapProvider:
    """A core sitemap provider backed by cms published posts.

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

    def __init__(
        self,
        post_loader,
        public_base_url_provider: Optional[Callable[[], str]] = None,
    ) -> None:
        self._post_loader = post_loader
        self._public_base_url_provider = public_base_url_provider or (lambda: "")

    def sitemap_entries(self) -> List[SitemapEntry]:
        entries: List[SitemapEntry] = []
        for post in self._post_loader.iter_candidate_posts():
            terms = self._post_loader.terms_for(post)
            if not page_is_search_visible(_ScopeView(post, terms)):
                continue
            entries.append(self._entry_for(post))
        return entries

    def _public_base_url(self) -> str:
        return (self._public_base_url_provider() or "").rstrip("/")

    def _loc_for(self, canonical_url: Optional[str], slug: Optional[str]) -> str:
        """Absolute URL for a post: stored canonical, else base + slug."""
        if canonical_url:
            return canonical_url
        return f"{self._public_base_url()}/{(slug or '').lstrip('/')}"

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


class _ScopeView:
    """Adapts (post, terms) into the duck-typed shape the predicate expects."""

    def __init__(self, post, terms) -> None:
        self.status = post.status
        self.seo_excluded = post.seo_excluded
        self.robots = post.robots
        self.terms = terms or []
