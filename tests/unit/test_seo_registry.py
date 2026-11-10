"""cms SEO seam — sitemap-provider registry v2 (S154 P1, D2).

A v2 provider exposes a stable url-safe ``name``, ``count()`` and
``page(offset, limit)``, so the sitemap renders one chunk at a time and never
materialises every URL. Registration is idempotent by ``name`` (last one wins,
position kept). Legacy list-style providers (``sitemap_entries()``) keep
working through an adapter (count = len, page = slice) — Liskov.

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(the adapter honours the v2 contract; the empty registry never crashes); clean
code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.services import seo_registry
from plugins.cms.src.services.seo_registry import (
    LegacySitemapProviderAdapter,
    SitemapEntry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    seo_registry.clear_sitemap_providers()
    yield
    seo_registry.clear_sitemap_providers()


class _NativeProvider:
    def __init__(self, name, locs=()):
        self.name = name
        self._entries = [SitemapEntry(loc=loc) for loc in locs]

    def count(self):
        return len(self._entries)

    def page(self, offset, limit):
        return self._entries[offset : offset + limit]


class LegacyBlogProvider:
    def __init__(self, locs=()):
        self._entries = [SitemapEntry(loc=loc) for loc in locs]

    def sitemap_entries(self):
        return list(self._entries)


def test_empty_registry_lists_no_providers():
    """Liskov null default: zero providers ⇒ empty list, never a crash."""
    assert seo_registry.list_sitemap_providers() == []


def test_native_provider_is_registered_as_is():
    provider = _NativeProvider("shop-products")
    seo_registry.register_sitemap_provider(provider)
    assert seo_registry.list_sitemap_providers() == [provider]
    assert seo_registry.find_sitemap_provider("shop-products") is provider


def test_registration_is_idempotent_by_name_and_keeps_position():
    first = _NativeProvider("cms")
    other = _NativeProvider("shop")
    replacement = _NativeProvider("cms")
    seo_registry.register_sitemap_provider(first)
    seo_registry.register_sitemap_provider(other)
    seo_registry.register_sitemap_provider(first)
    seo_registry.register_sitemap_provider(replacement)

    assert seo_registry.list_sitemap_providers() == [replacement, other]


@pytest.mark.parametrize("bad_name", ["", "Shop", "shop products", "a/b", "-x", "x-"])
def test_non_url_safe_name_is_rejected(bad_name):
    with pytest.raises(ValueError):
        seo_registry.register_sitemap_provider(_NativeProvider(bad_name))


def test_object_without_a_provider_shape_is_rejected():
    with pytest.raises(TypeError):
        seo_registry.register_sitemap_provider(object())


def test_legacy_provider_is_adapted_to_v2():
    legacy = LegacyBlogProvider(["https://x/a", "https://x/b", "https://x/c"])
    seo_registry.register_sitemap_provider(legacy)

    (adapted,) = seo_registry.list_sitemap_providers()
    assert isinstance(adapted, LegacySitemapProviderAdapter)
    assert adapted.name == "legacy-blog-provider"
    assert adapted.count() == 3
    assert [entry.loc for entry in adapted.page(1, 5)] == ["https://x/b", "https://x/c"]
    assert list(adapted.page(3, 5)) == []


def test_reregistering_an_adapter_keeps_it_unwrapped():
    """A snapshot from ``list_sitemap_providers`` re-registers unchanged."""
    seo_registry.register_sitemap_provider(LegacyBlogProvider(["https://x/a"]))
    snapshot = seo_registry.list_sitemap_providers()
    seo_registry.clear_sitemap_providers()
    for provider in snapshot:
        seo_registry.register_sitemap_provider(provider)
    assert seo_registry.list_sitemap_providers() == snapshot


def test_unregister_removes_native_and_legacy_providers():
    native = _NativeProvider("shop")
    legacy = LegacyBlogProvider()
    seo_registry.register_sitemap_provider(native)
    seo_registry.register_sitemap_provider(legacy)

    seo_registry.unregister_sitemap_provider(native)
    seo_registry.unregister_sitemap_provider(legacy)
    seo_registry.unregister_sitemap_provider(legacy)

    assert seo_registry.list_sitemap_providers() == []


def test_find_unknown_provider_returns_none():
    assert seo_registry.find_sitemap_provider("nope") is None


def test_sitemap_entry_defaults():
    """Optional fields default sensibly; only ``loc`` is required."""
    entry = SitemapEntry(loc="https://x/a")
    assert entry.loc == "https://x/a"
    assert entry.lastmod is None
    assert entry.changefreq is None
    assert entry.priority is None
    assert entry.alternates == []
