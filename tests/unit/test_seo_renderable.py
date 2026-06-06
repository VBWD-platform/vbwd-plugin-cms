"""cms SEO seam — the duck-typed ``SeoRenderable`` protocol (moved in S50.2).

The meta-builder consumes THIS protocol, not a concrete ``cms_post``, so a
future content plugin (or a non-cms stub) feeds the same SEO pipeline. This
test proves a hand-rolled stub satisfies the protocol via ``isinstance``
(runtime-checkable).

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov;
clean code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from plugins.cms.src.services.seo_renderable import SeoRenderable, SeoSibling


@dataclass
class _PlainRenderable:
    """A minimal stub — proves the protocol is satisfied structurally."""

    slug: str = "about"
    language: str = "en"
    robots: str = "index,follow"
    meta_title: Optional[str] = "About us"
    meta_description: Optional[str] = "Who we are"
    meta_keywords: Optional[str] = "about, team"
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image_url: Optional[str] = None
    canonical_url: Optional[str] = "https://x/about"
    schema_json: Optional[dict] = None
    translation_siblings: List[SeoSibling] = field(default_factory=list)

    def is_search_visible(self) -> bool:
        return True


def test_plain_stub_satisfies_protocol():
    stub = _PlainRenderable()
    assert isinstance(stub, SeoRenderable)


def test_stub_accessors_callable():
    stub = _PlainRenderable()
    assert stub.is_search_visible() is True
    assert stub.slug == "about"
    assert stub.canonical_url == "https://x/about"


def test_object_missing_accessor_is_not_renderable():
    class Incomplete:
        slug = "x"
        language = "en"

    assert not isinstance(Incomplete(), SeoRenderable)
