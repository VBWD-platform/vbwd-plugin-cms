"""S154 P1 — sitemap chunk planning over v2 providers (no full materialisation).

``SitemapChunker`` turns provider counts into ``/sitemap-<name>-<n>.xml`` chunk
references and renders ONE chunk through ``provider.page(offset, cap)``. The
index only calls ``count()``; a chunk calls ``page()`` exactly once. Private
paths (cms ``seo_private_path_prefixes``) are filtered centrally (D1), so a
chunk may hold fewer than ``cap`` URLs.

Engineering requirements (binding, restated): TDD-first; SOLID (planning is
separate from rendering); DI (providers + prefixes + cap injected); DRY;
Liskov; clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services.seo_registry import SitemapEntry
from plugins.cms.src.services.seo_sitemap_chunks import (
    SITEMAP_URL_CAP,
    SitemapChunkRef,
    SitemapChunker,
)

LARGE_PROVIDER_SIZE = 120000


class _RecordingProvider:
    """Reports ``size`` URLs; generates only the requested page, records calls."""

    def __init__(self, name, size, loc_for=None):
        self.name = name
        self._size = size
        self._loc_for = loc_for or (lambda index: f"https://x/{name}/{index}")
        self.page_calls = []

    def count(self):
        return self._size

    def page(self, offset, limit):
        self.page_calls.append((offset, limit))
        stop = min(offset + limit, self._size)
        return (SitemapEntry(loc=self._loc_for(index)) for index in range(offset, stop))


def test_default_cap_is_the_sitemaps_org_limit():
    assert SITEMAP_URL_CAP == 50000


def test_chunk_refs_follow_counts_without_paging():
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    refs = SitemapChunker([provider]).chunk_refs()

    assert refs == [
        SitemapChunkRef("fake", 1),
        SitemapChunkRef("fake", 2),
        SitemapChunkRef("fake", 3),
    ]
    assert refs[1].filename == "sitemap-fake-2.xml"
    assert provider.page_calls == []


def test_chunk_refs_keep_provider_order_and_skip_empty_providers():
    providers = [
        _RecordingProvider("cms", 3),
        _RecordingProvider("empty", 0),
        _RecordingProvider("shop", 2),
    ]
    refs = SitemapChunker(providers, url_cap=2).chunk_refs()
    assert [ref.filename for ref in refs] == [
        "sitemap-cms-1.xml",
        "sitemap-cms-2.xml",
        "sitemap-shop-1.xml",
    ]


def test_chunk_entries_pages_exactly_once_at_the_chunk_offset():
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    entries = SitemapChunker([provider]).chunk_entries("fake", 2)

    assert provider.page_calls == [(50000, 50000)]
    assert len(entries) == 50000
    assert entries[0].loc == "https://x/fake/50000"


def test_last_chunk_holds_the_remainder():
    provider = _RecordingProvider("fake", 5)
    entries = SitemapChunker([provider], url_cap=2).chunk_entries("fake", 3)
    assert [entry.loc for entry in entries] == ["https://x/fake/4"]


def test_out_of_range_or_unknown_chunk_is_none_without_paging():
    provider = _RecordingProvider("fake", LARGE_PROVIDER_SIZE)
    chunker = SitemapChunker([provider])

    assert chunker.chunk_entries("fake", 0) is None
    assert chunker.chunk_entries("fake", 4) is None
    assert chunker.chunk_entries("unknown", 1) is None
    assert provider.page_calls == []


def test_private_paths_are_filtered_centrally():
    locs = [
        "https://x/dashboard/orders",
        "/pay",
        "https://x/payments-guide",
        "/software/checkout",
        "https://x/about",
    ]
    provider = _RecordingProvider("mixed", len(locs), loc_for=locs.__getitem__)
    chunker = SitemapChunker(
        [provider], private_path_prefixes=("/dashboard", "/pay", "/software")
    )
    entries = chunker.chunk_entries("mixed", 1)
    assert [entry.loc for entry in entries] == [
        "https://x/payments-guide",
        "https://x/about",
    ]


def test_legacy_global_number_maps_onto_provider_chunks():
    providers = [_RecordingProvider("cms", 3), _RecordingProvider("shop", 2)]
    chunker = SitemapChunker(providers, url_cap=2)

    assert chunker.legacy_chunk_ref(1) == SitemapChunkRef("cms", 1)
    assert chunker.legacy_chunk_ref(2) == SitemapChunkRef("cms", 2)
    assert chunker.legacy_chunk_ref(3) == SitemapChunkRef("shop", 1)
    assert chunker.legacy_chunk_ref(0) is None
    assert chunker.legacy_chunk_ref(4) is None
