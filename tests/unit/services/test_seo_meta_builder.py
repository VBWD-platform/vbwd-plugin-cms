"""S47.1 — the meta-builder: SeoRenderable → head tags + JSON-LD.

The builder consumes the core duck-typed ``SeoRenderable`` (not a cms_post),
emits self-canonical, og/twitter, robots, hreflang (+ x-default), and per-type
JSON-LD via a schema mapper registry. Everything HTML-escaped.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from plugins.cms.src.services.seo_meta_builder import (
    build_meta,
    register_schema_mapper,
    build_breadcrumb_jsonld,
    build_organization_jsonld,
)


@dataclass
class _Sibling:
    language: str
    canonical_url: Optional[str]


@dataclass
class _Renderable:
    slug: str = "pricing"
    language: str = "en"
    robots: str = "index,follow"
    meta_title: Optional[str] = "Pricing"
    meta_description: Optional[str] = "Our plans"
    meta_keywords: Optional[str] = "pricing, plans"
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image_url: Optional[str] = "https://x/og.png"
    canonical_url: Optional[str] = "https://x/en/pricing"
    schema_json: Optional[dict] = None
    schema_type: str = "WebPage"
    title: str = "Pricing"
    translation_siblings: List[_Sibling] = field(default_factory=list)

    def is_search_visible(self) -> bool:
        return self.robots and "noindex" not in self.robots


def _head_text(tags):
    return "\n".join(tags)


def test_title_and_description_tags():
    tags, _ = build_meta(_Renderable())
    text = _head_text(tags)
    assert "<title>Pricing</title>" in text
    assert '<meta name="description" content="Our plans"' in text
    assert '<meta name="keywords" content="pricing, plans"' in text


def test_self_canonical():
    tags, _ = build_meta(_Renderable())
    text = _head_text(tags)
    assert '<link rel="canonical" href="https://x/en/pricing"' in text


def test_robots_tag():
    tags, _ = build_meta(_Renderable(robots="noindex,nofollow"))
    assert '<meta name="robots" content="noindex,nofollow"' in _head_text(tags)


def test_og_falls_back_to_meta_when_absent():
    tags, _ = build_meta(_Renderable(og_title=None, og_description=None))
    text = _head_text(tags)
    assert '<meta property="og:title" content="Pricing"' in text
    assert '<meta property="og:description" content="Our plans"' in text


def test_og_uses_explicit_when_present():
    tags, _ = build_meta(_Renderable(og_title="Buy now", og_description="Deals"))
    text = _head_text(tags)
    assert '<meta property="og:title" content="Buy now"' in text


def test_og_image_and_twitter():
    tags, _ = build_meta(_Renderable())
    text = _head_text(tags)
    assert '<meta property="og:image" content="https://x/og.png"' in text
    assert '<meta name="twitter:card" content="summary_large_image"' in text
    assert '<meta name="twitter:title" content="Pricing"' in text


def test_html_escaping():
    page = _Renderable(meta_title="A & B <x>", meta_description='"quote"')
    tags, _ = build_meta(page)
    text = _head_text(tags)
    assert "<x>" not in text
    assert "A &amp; B &lt;x&gt;" in text
    assert "&quot;quote&quot;" in text


def test_hreflang_alternates_with_x_default():
    page = _Renderable(
        translation_siblings=[
            _Sibling(language="de", canonical_url="https://x/de/pricing"),
            _Sibling(language="fr", canonical_url="https://x/fr/pricing"),
        ]
    )
    tags, _ = build_meta(page)
    text = _head_text(tags)
    assert '<link rel="alternate" hreflang="en" href="https://x/en/pricing"' in text
    assert '<link rel="alternate" hreflang="de" href="https://x/de/pricing"' in text
    assert '<link rel="alternate" hreflang="fr" href="https://x/fr/pricing"' in text
    assert 'hreflang="x-default"' in text


def test_jsonld_webpage_default():
    _, jsonld = build_meta(_Renderable(schema_type="WebPage"))
    assert jsonld["@type"] == "WebPage"
    assert jsonld["name"] == "Pricing"
    assert jsonld["url"] == "https://x/en/pricing"


def test_jsonld_article_mapper():
    _, jsonld = build_meta(_Renderable(schema_type="Article"))
    assert jsonld["@type"] == "Article"
    assert jsonld["headline"] == "Pricing"


def test_author_schema_json_overrides():
    custom = {"@type": "Product", "name": "Custom"}
    _, jsonld = build_meta(_Renderable(schema_json=custom))
    assert jsonld == custom


def test_breadcrumb_jsonld():
    crumbs = [
        {"name": "Home", "url": "https://x/"},
        {"name": "About", "url": "https://x/about"},
        {"name": "Team", "url": "https://x/about/team"},
    ]
    jsonld = build_breadcrumb_jsonld(crumbs)
    assert jsonld["@type"] == "BreadcrumbList"
    assert len(jsonld["itemListElement"]) == 3
    assert jsonld["itemListElement"][0]["position"] == 1
    assert jsonld["itemListElement"][2]["item"]["name"] == "Team"


def test_organization_jsonld():
    jsonld = build_organization_jsonld(
        name="VBWD", url="https://x", logo="https://x/l.png"
    )
    assert jsonld["@type"] == "Organization"
    assert jsonld["name"] == "VBWD"
    assert jsonld["logo"] == "https://x/l.png"


def test_register_custom_schema_mapper():
    def faq_mapper(renderable):
        return {"@context": "https://schema.org", "@type": "FAQPage"}

    register_schema_mapper("FAQPage", faq_mapper)
    _, jsonld = build_meta(_Renderable(schema_type="FAQPage"))
    assert jsonld["@type"] == "FAQPage"
