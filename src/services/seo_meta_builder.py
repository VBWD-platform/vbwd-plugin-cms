"""The meta-builder: ``SeoRenderable`` → (head tags, JSON-LD) — S47.1 §3.

ONE field→tag mapping, consumed by the server prerender writer (47.1) and the
client meta-injection (47.2/47.3). It takes the core duck-typed
``SeoRenderable`` (not a ``cms_post``), so future content plugins feed the same
pipeline. Per-type JSON-LD lives in a ``schema_type → mapper`` registry; an
author-supplied ``schema_json`` overrides the mapper. Everything is
HTML-escaped.
"""
from typing import Callable, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

SCHEMA_ORG_CONTEXT = "https://schema.org"
TWITTER_CARD = "summary_large_image"


def _attr(value: str) -> str:
    """Escape an attribute value and wrap it in double quotes.

    Unlike ``saxutils.quoteattr`` (which switches to single quotes when the
    value contains a double quote), we always emit double-quoted attributes
    with ``"`` escaped to ``&quot;`` for a stable, predictable ``<head>``.
    """
    escaped = escape(value or "", {'"': "&quot;"})
    return f'"{escaped}"'


def _meta_name(name: str, content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    return f'<meta name="{name}" content={_attr(content)} />'


def _meta_property(prop: str, content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    return f'<meta property="{prop}" content={_attr(content)} />'


def _title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return f"<title>{escape(value)}</title>"


def _link(rel: str, href: Optional[str], hreflang: Optional[str] = None):
    if not href:
        return None
    if hreflang:
        return f'<link rel="{rel}" hreflang="{escape(hreflang)}" href={_attr(href)} />'
    return f'<link rel="{rel}" href={_attr(href)} />'


def _resolve_title(renderable) -> str:
    title = (
        getattr(renderable, "meta_title", None)
        or getattr(renderable, "title", None)
        or getattr(renderable, "slug", "")
    )
    return str(title or "")


# ── JSON-LD mappers (schema_type → JSON-LD) ──────────────────────────────────

SchemaMapper = Callable[[object], Dict]


def _webpage_mapper(renderable) -> Dict:
    return {
        "@context": SCHEMA_ORG_CONTEXT,
        "@type": "WebPage",
        "name": _resolve_title(renderable),
        "url": getattr(renderable, "canonical_url", None),
        "description": getattr(renderable, "meta_description", None),
    }


def _article_mapper(renderable) -> Dict:
    return {
        "@context": SCHEMA_ORG_CONTEXT,
        "@type": "Article",
        "headline": _resolve_title(renderable),
        "url": getattr(renderable, "canonical_url", None),
        "description": getattr(renderable, "meta_description", None),
    }


_schema_mappers: Dict[str, SchemaMapper] = {
    "WebPage": _webpage_mapper,
    "Article": _article_mapper,
}


def register_schema_mapper(schema_type: str, mapper: SchemaMapper) -> None:
    """Register (or replace) a ``schema_type → JSON-LD`` mapper."""
    _schema_mappers[schema_type] = mapper


def build_breadcrumb_jsonld(crumbs: List[Dict[str, str]]) -> Dict:
    """``BreadcrumbList`` from a parent/term path (``[{name, url}]``)."""
    return {
        "@context": SCHEMA_ORG_CONTEXT,
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index + 1,
                "item": {"@id": crumb["url"], "name": crumb["name"]},
            }
            for index, crumb in enumerate(crumbs)
        ],
    }


def build_organization_jsonld(name: str, url: str, logo: Optional[str] = None) -> Dict:
    """Site-level ``Organization`` JSON-LD."""
    data: Dict = {
        "@context": SCHEMA_ORG_CONTEXT,
        "@type": "Organization",
        "name": name,
        "url": url,
    }
    if logo:
        data["logo"] = logo
    return data


def build_website_jsonld(name: str, url: str) -> Dict:
    """Site-level ``WebSite`` JSON-LD."""
    return {
        "@context": SCHEMA_ORG_CONTEXT,
        "@type": "WebSite",
        "name": name,
        "url": url,
    }


def _build_jsonld(renderable) -> Dict:
    author = getattr(renderable, "schema_json", None)
    if author:
        return author
    schema_type = getattr(renderable, "schema_type", "WebPage") or "WebPage"
    mapper = _schema_mappers.get(schema_type, _webpage_mapper)
    return mapper(renderable)


# ── hreflang ─────────────────────────────────────────────────────────────────


def _hreflang_tags(renderable) -> List[str]:
    """Self + sibling alternates (+ x-default = self)."""
    self_canonical = getattr(renderable, "canonical_url", None)
    self_language = getattr(renderable, "language", None)
    if not self_canonical or not self_language:
        return []

    tags: List[str] = []
    self_tag = _link("alternate", self_canonical, hreflang=self_language)
    if self_tag:
        tags.append(self_tag)
    for sibling in getattr(renderable, "translation_siblings", None) or []:
        sibling_tag = _link(
            "alternate", sibling.canonical_url, hreflang=sibling.language
        )
        if sibling_tag:
            tags.append(sibling_tag)
    default_tag = _link("alternate", self_canonical, hreflang="x-default")
    if default_tag:
        tags.append(default_tag)
    return tags


# ── public entry point ───────────────────────────────────────────────────────


def build_meta(renderable) -> Tuple[List[str], Dict]:
    """Build the ``<head>`` tag list + JSON-LD for a renderable."""
    title = _resolve_title(renderable)
    description = getattr(renderable, "meta_description", None)
    og_title = getattr(renderable, "og_title", None) or title
    og_description = getattr(renderable, "og_description", None) or description

    raw_tags = [
        _title(title),
        _meta_name("description", description),
        _meta_name("keywords", getattr(renderable, "meta_keywords", None)),
        _meta_name("robots", getattr(renderable, "robots", None)),
        _link("canonical", getattr(renderable, "canonical_url", None)),
        _meta_property("og:title", og_title),
        _meta_property("og:description", og_description),
        _meta_property("og:image", getattr(renderable, "og_image_url", None)),
        _meta_name("twitter:card", TWITTER_CARD),
        _meta_name("twitter:title", og_title),
        _meta_name("twitter:description", og_description),
        _meta_name("twitter:image", getattr(renderable, "og_image_url", None)),
    ]
    tags = [tag for tag in raw_tags if tag]
    tags.extend(_hreflang_tags(renderable))

    return tags, _build_jsonld(renderable)
