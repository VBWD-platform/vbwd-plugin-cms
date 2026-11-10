"""Sitemap chunk planning over registry-v2 providers (S154 P1, D1/D2).

Turns provider ``count()``s into ``/sitemap-<name>-<n>.xml`` chunk references
and reads ONE chunk through ``provider.page((n - 1) * cap, cap)`` — so no
request ever materialises more than one chunk, whatever the catalogue size.

Private paths (cms ``seo_private_path_prefixes``) are dropped here, centrally,
for every provider (D1). A chunk can therefore hold fewer than ``cap`` URLs —
valid per sitemaps.org (the cap is a maximum), and it keeps chunk numbering a
pure function of ``count()``.
"""
from dataclasses import dataclass
from typing import List, Optional, Sequence
from urllib.parse import urlsplit

from plugins.cms.src.services.seo_registry import ISitemapProvider, SitemapEntry
from plugins.cms.src.services.seo_scope import path_is_private

# sitemaps.org caps a single sitemap file at 50,000 URLs.
SITEMAP_URL_CAP = 50000


@dataclass(frozen=True)
class SitemapChunkRef:
    """The ``number``-th (1-based) chunk of one provider."""

    provider_name: str
    number: int

    @property
    def filename(self) -> str:
        return f"sitemap-{self.provider_name}-{self.number}.xml"


class SitemapChunker:
    """Plans and reads sitemap chunks for a fixed list of providers."""

    def __init__(
        self,
        providers: Sequence[ISitemapProvider],
        private_path_prefixes: Sequence[str] = (),
        url_cap: int = SITEMAP_URL_CAP,
    ) -> None:
        self._providers = list(providers)
        self._private_path_prefixes = tuple(private_path_prefixes)
        self._url_cap = url_cap

    def chunk_refs(self) -> List[SitemapChunkRef]:
        """Every chunk of every provider, in registration order (counts only)."""
        return [
            SitemapChunkRef(provider.name, number)
            for provider in self._providers
            for number in range(1, self._chunk_count(provider) + 1)
        ]

    def chunk_entries(
        self, provider_name: str, number: int
    ) -> Optional[List[SitemapEntry]]:
        """The public entries of one chunk, or ``None`` when it does not exist."""
        provider = self._find(provider_name)
        if provider is None or not 1 <= number <= self._chunk_count(provider):
            return None
        page = provider.page((number - 1) * self._url_cap, self._url_cap)
        return [entry for entry in page if not self._is_private(entry)]

    def legacy_chunk_ref(self, global_number: int) -> Optional[SitemapChunkRef]:
        """Map a pre-S154 ``/sitemap-<n>.xml`` number onto the n-th index chunk."""
        refs = self.chunk_refs()
        if not 1 <= global_number <= len(refs):
            return None
        return refs[global_number - 1]

    def _chunk_count(self, provider: ISitemapProvider) -> int:
        url_count = max(provider.count(), 0)
        return (url_count + self._url_cap - 1) // self._url_cap

    def _find(self, provider_name: str) -> Optional[ISitemapProvider]:
        for provider in self._providers:
            if provider.name == provider_name:
                return provider
        return None

    def _is_private(self, entry: SitemapEntry) -> bool:
        return path_is_private(urlsplit(entry.loc).path, self._private_path_prefixes)
