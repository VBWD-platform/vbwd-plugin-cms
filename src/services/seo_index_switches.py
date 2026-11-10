"""Which cms content types are indexable (S154 P2 owner requirement).

Four fe-admin switches (cms plugin settings, ``config.json`` defaults) decide
which cms URL families reach the sitemap:

* ``seo_index_pages``      — ``type == "page"`` posts (default on);
* ``seo_index_posts``      — ``type == "post"`` posts (default on);
* ``seo_index_categories`` — ``/category/<slug>`` archives (default off);
* ``seo_index_tags``       — ``/tag/<slug>`` archives (default off).

Precedence (one rule, read per request): a saved, non-null new key wins; else
the pre-S154 key it replaces (only pages has one: ``sitemap_include_pages``);
else the default. ``get_config`` returns the SAVED blob only (no schema
defaults), so "saved" is a plain key-presence check.
"""
from dataclasses import dataclass
from typing import Optional

SEO_INDEX_PAGES_KEY = "seo_index_pages"
SEO_INDEX_POSTS_KEY = "seo_index_posts"
SEO_INDEX_CATEGORIES_KEY = "seo_index_categories"
SEO_INDEX_TAGS_KEY = "seo_index_tags"

# The pre-S154 key folded into ``seo_index_pages`` (read for back-compat).
LEGACY_INCLUDE_PAGES_KEY = "sitemap_include_pages"

SEO_INDEX_CONFIG_KEYS = (
    SEO_INDEX_PAGES_KEY,
    SEO_INDEX_POSTS_KEY,
    SEO_INDEX_CATEGORIES_KEY,
    SEO_INDEX_TAGS_KEY,
)


@dataclass(frozen=True)
class SeoIndexSwitches:
    """The effective on/off state of each indexable cms content type."""

    pages: bool
    posts: bool
    categories: bool
    tags: bool


def _saved_flag(config: dict, key: str) -> Optional[bool]:
    value = config.get(key)
    return None if value is None else bool(value)


def _resolve_flag(
    config: dict, key: str, default: bool, legacy_key: Optional[str] = None
) -> bool:
    saved = _saved_flag(config, key)
    if saved is None and legacy_key is not None:
        saved = _saved_flag(config, legacy_key)
    return default if saved is None else saved


def resolve_seo_index_switches(config: Optional[dict]) -> SeoIndexSwitches:
    """Resolve the four switches from a (saved) cms config blob."""
    config = config or {}
    return SeoIndexSwitches(
        pages=_resolve_flag(
            config, SEO_INDEX_PAGES_KEY, True, legacy_key=LEGACY_INCLUDE_PAGES_KEY
        ),
        posts=_resolve_flag(config, SEO_INDEX_POSTS_KEY, True),
        categories=_resolve_flag(config, SEO_INDEX_CATEGORIES_KEY, False),
        tags=_resolve_flag(config, SEO_INDEX_TAGS_KEY, False),
    )
