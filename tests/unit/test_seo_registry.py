"""cms SEO seam — sitemap-provider registry (moved from core in S50.2).

cms owns ``ISeoSitemapProvider`` + ``SitemapEntry`` + an aggregator that
returns ``[]`` when no provider is registered (Liskov null default). cms
registers its own published-post provider; other content plugins may register
theirs too.

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(null default never crashes); clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.services import seo_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    seo_registry.clear_sitemap_providers()
    yield
    seo_registry.clear_sitemap_providers()


def test_aggregator_returns_empty_with_no_providers():
    """Liskov null default: zero providers ⇒ empty list, never a crash."""
    assert seo_registry.aggregate_sitemap_entries() == []


def test_aggregator_collects_entries_from_all_providers():
    entry_one = seo_registry.SitemapEntry(loc="https://x/a", lastmod="2026-01-01")
    entry_two = seo_registry.SitemapEntry(loc="https://x/b", lastmod="2026-01-02")

    class ProviderA:
        def sitemap_entries(self):
            return [entry_one]

    class ProviderB:
        def sitemap_entries(self):
            return [entry_two]

    seo_registry.register_sitemap_provider(ProviderA())
    seo_registry.register_sitemap_provider(ProviderB())

    entries = seo_registry.aggregate_sitemap_entries()
    locs = {entry.loc for entry in entries}
    assert locs == {"https://x/a", "https://x/b"}


def test_sitemap_entry_defaults():
    """Optional fields default sensibly; only ``loc`` is required."""
    entry = seo_registry.SitemapEntry(loc="https://x/a")
    assert entry.loc == "https://x/a"
    assert entry.lastmod is None
    assert entry.changefreq is None
    assert entry.priority is None
    assert entry.alternates == []


def test_list_sitemap_providers_returns_registered():
    class Provider:
        def sitemap_entries(self):
            return []

    provider = Provider()
    seo_registry.register_sitemap_provider(provider)
    assert provider in seo_registry.list_sitemap_providers()
