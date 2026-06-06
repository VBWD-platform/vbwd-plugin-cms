"""The ``SeoRenderable`` protocol — what the meta-builder consumes.

The cms meta-builder (S47.1) builds ``<head>`` tags + JSON-LD from THIS
duck-typed protocol, not from a concrete ``cms_post``. So a future content
plugin (shop product pages, a docs plugin) feeds the exact same SEO pipeline
by exposing these fields.

A renderable exposes its identity (slug, language, canonical), its SEO
columns (meta_*, og_*, robots, schema_json), its translation siblings (for
hreflang), and a single ``is_search_visible()`` accessor (the plugin owns the
visibility rule; the meta-builder/sitemap just ask).
"""
from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class SeoSibling(Protocol):
    """A translation sibling used to build hreflang alternates."""

    language: str
    canonical_url: Optional[str]


@runtime_checkable
class SeoRenderable(Protocol):
    """SEO/identity surface a content object exposes to the meta-builder."""

    slug: str
    language: str
    robots: str
    meta_title: Optional[str]
    meta_description: Optional[str]
    meta_keywords: Optional[str]
    og_title: Optional[str]
    og_description: Optional[str]
    og_image_url: Optional[str]
    canonical_url: Optional[str]
    schema_json: Optional[dict]
    translation_siblings: List[SeoSibling]

    def is_search_visible(self) -> bool:
        """True when this object may be indexed (plugin owns the rule)."""
        ...
