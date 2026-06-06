"""Registry of sitemap providers (plugin-contributed) — cms-owned seam.

cms's ``/sitemap.xml`` aggregates every registered provider's entries. cms
declares one provider of its own (the published-post provider); other content
plugins could register theirs too. With nothing registered the aggregator
returns ``[]`` — the route still serves a valid, empty urlset (Liskov null
default), never a crash.

The provider is duck-typed via ``ISeoSitemapProvider``: any object exposing
``sitemap_entries() -> list[SitemapEntry]`` qualifies, so no plugin module is
imported here.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class SitemapEntry:
    """One ``<url>`` in the sitemap.

    ``alternates`` carries hreflang siblings as ``{"hreflang", "href"}`` dicts
    (rendered as ``xhtml:link`` elements). Only ``loc`` is required.
    """

    loc: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[str] = None
    alternates: List[Dict[str, str]] = field(default_factory=list)


@runtime_checkable
class ISeoSitemapProvider(Protocol):
    """A source of sitemap entries (e.g. cms published posts)."""

    def sitemap_entries(self) -> List[SitemapEntry]:
        """Return the search-visible entries this provider owns."""
        ...


_providers: List[ISeoSitemapProvider] = []


def register_sitemap_provider(provider: ISeoSitemapProvider) -> None:
    """Register a sitemap provider (plugin enable)."""
    if provider not in _providers:
        _providers.append(provider)


def unregister_sitemap_provider(provider: ISeoSitemapProvider) -> None:
    """Remove a sitemap provider (plugin disable)."""
    if provider in _providers:
        _providers.remove(provider)


def clear_sitemap_providers() -> None:
    """Reset all providers (test teardown)."""
    _providers.clear()


def list_sitemap_providers() -> List[ISeoSitemapProvider]:
    """Return the registered providers."""
    return list(_providers)


def aggregate_sitemap_entries() -> List[SitemapEntry]:
    """Collect entries from every registered provider (``[]`` with none)."""
    entries: List[SitemapEntry] = []
    for provider in _providers:
        entries.extend(provider.sitemap_entries())
    return entries
