"""Registry of sitemap providers (plugin-contributed) — cms-owned seam.

cms serves ``/sitemap.xml`` as a sitemap index of per-provider chunk files
(``/sitemap-<name>-<n>.xml``). Any plugin with public pages registers ONE
provider per URL family from its ``on_enable`` (only when cms is enabled — cms
is an optional dependency, D3) and unregisters it in ``on_disable``. cms never
imports a domain plugin: the contract below is duck-typed.

Provider contract v2 (S154, D2) — ``ISitemapProvider``:

* ``name`` — stable, url-safe id (``[a-z0-9]`` words joined by single ``-``,
  e.g. ``cms``, ``shop-products``). It is part of the public chunk URL, so it
  must never change once published.
* ``count() -> int`` — the length of the stable sequence ``page()`` walks.
* ``page(offset, limit) -> Iterable[SitemapEntry]`` — at most ``limit``
  entries starting at ``offset`` of that sequence, in a STABLE order (keyset
  or ``ORDER BY <indexed column> LIMIT/OFFSET``; never load every row).

A provider describes **public, indexable URLs only** (D1). ``page()`` may drop
rows it filters (and cms drops private paths centrally), so a chunk may hold
fewer than the cap; ``count()`` is therefore an upper bound on emitted URLs.

Legacy list-style providers (``sitemap_entries() -> list``) keep working: they
are wrapped by ``LegacySitemapProviderAdapter`` (count = len, page = slice).
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Protocol, runtime_checkable

PROVIDER_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
class ISitemapProvider(Protocol):
    """A paged source of sitemap entries (registry v2, see module docstring)."""

    @property
    def name(self) -> str:
        """Stable url-safe identifier used in ``/sitemap-<name>-<n>.xml``."""
        ...

    def count(self) -> int:
        """Length of the stable sequence ``page()`` walks."""
        ...

    def page(self, offset: int, limit: int) -> Iterable[SitemapEntry]:
        """At most ``limit`` entries from ``offset``, in a stable order."""
        ...


@runtime_checkable
class ILegacySitemapProvider(Protocol):
    """The pre-v2 list-style provider shape (still accepted, adapted)."""

    def sitemap_entries(self) -> List[SitemapEntry]:
        """Return every search-visible entry this provider owns."""
        ...


def _kebab_case(class_name: str) -> str:
    """``LegacyBlogProvider`` -> ``legacy-blog-provider`` (url-safe)."""
    split_words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", class_name).lower()
    return re.sub(r"[^a-z0-9]+", "-", split_words).strip("-") or "legacy"


class LegacySitemapProviderAdapter:
    """Presents a list-style provider through the v2 contract (Liskov).

    The name is derived from the wrapped provider's class name; ``count`` and
    ``page`` each read the full legacy list — acceptable for the small,
    in-memory providers that still use the old shape.
    """

    def __init__(self, legacy_provider: ILegacySitemapProvider) -> None:
        self._legacy_provider = legacy_provider
        self.name = _kebab_case(type(legacy_provider).__name__)

    def count(self) -> int:
        return len(self._legacy_provider.sitemap_entries())

    def page(self, offset: int, limit: int) -> List[SitemapEntry]:
        return self._legacy_provider.sitemap_entries()[offset : offset + limit]


_providers: Dict[str, ISitemapProvider] = {}


def _as_v2_provider(provider: object) -> ISitemapProvider:
    """Accept a v2 provider as-is; wrap a legacy one; reject anything else."""
    if isinstance(provider, ISitemapProvider):
        return provider
    if isinstance(provider, ILegacySitemapProvider):
        return LegacySitemapProviderAdapter(provider)
    raise TypeError(
        f"{type(provider).__name__} is not a sitemap provider: expose "
        "name/count()/page(offset, limit) (or legacy sitemap_entries())"
    )


def register_sitemap_provider(provider: object) -> None:
    """Register (or replace, by ``name``) a sitemap provider — plugin enable.

    Idempotent by name: a second registration under the same name replaces the
    first in place, so a re-enable never duplicates a chunk family.
    """
    sitemap_provider = _as_v2_provider(provider)
    if not PROVIDER_NAME_PATTERN.match(sitemap_provider.name or ""):
        raise ValueError(
            f"sitemap provider name {sitemap_provider.name!r} is not url-safe "
            "(lower-case letters/digits joined by single '-')"
        )
    _providers[sitemap_provider.name] = sitemap_provider


def unregister_sitemap_provider(provider: object) -> None:
    """Remove the provider registered under ``provider``'s name — plugin disable."""
    _providers.pop(_as_v2_provider(provider).name, None)


def clear_sitemap_providers() -> None:
    """Reset all providers (test teardown)."""
    _providers.clear()


def list_sitemap_providers() -> List[ISitemapProvider]:
    """Return the registered (v2) providers in registration order."""
    return list(_providers.values())


def find_sitemap_provider(name: str) -> Optional[ISitemapProvider]:
    """The provider registered under ``name``, or ``None``."""
    return _providers.get(name)
