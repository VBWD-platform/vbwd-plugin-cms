"""Canonical-URL fallback for prerendered pages (S121).

``cms_post.canonical_url`` is a nullable OVERRIDE, not a requirement. When a
published post has no stored ``canonical_url``, the prerender must still emit a
correct canonical URL derived from ``public_base_url + <path>`` — where the path
is ``/`` for the home slug (or an empty slug) and ``/<slug>`` otherwise (the
SAME rule the sitemap provider's ``_loc_for`` uses, so meta and sitemap agree).

Both the JSON-LD ``url`` and the ``<link rel="canonical">`` must carry that
effective value, and they must be CONSISTENT with each other. With no
``public_base_url`` configured the fallback is a root-relative path (never
``null``/absent).

Engineering requirements (binding, restated): TDD-first; DevOps-first;
SOLID/DI/DRY; Liskov; clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import json
import re

from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


class _Post:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "p1")
        self.type = kwargs.get("type", "page")
        self.slug = kwargs.get("slug", "docs")
        self.title = kwargs.get("title", "Docs")
        self.content_html = kwargs.get("content_html", "<p>Docs</p>")
        self.status = kwargs.get("status", POST_STATUS_PUBLISHED)
        self.language = kwargs.get("language", "en")
        self.robots = kwargs.get("robots", "index,follow")
        self.seo_excluded = kwargs.get("seo_excluded", False)
        self.meta_title = kwargs.get("meta_title", "Docs")
        self.meta_description = kwargs.get("meta_description", "The docs")
        self.meta_keywords = kwargs.get("meta_keywords", None)
        self.og_title = kwargs.get("og_title", None)
        self.og_description = kwargs.get("og_description", None)
        self.og_image_url = kwargs.get("og_image_url", None)
        # The bug under test: an empty (nullable) canonical column.
        self.canonical_url = kwargs.get("canonical_url", None)
        self.schema_json = kwargs.get("schema_json", None)
        self.translation_group_id = kwargs.get("translation_group_id", None)
        self.terms = kwargs.get("terms", [])


class _Loader:
    def __init__(self, posts):
        self._posts = {p.id: p for p in posts}

    def load(self, post_id):
        post = self._posts.get(post_id)
        if post is None:
            return None
        return post, post.terms, []


def _render(tmp_path, post, **kwargs):
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_Loader([post]),
        **kwargs,
    )
    writer.handle_content_changed(
        {"post_id": post.id, "slug": post.slug, "status": post.status}
    )
    return (tmp_path / "seo" / f"{post.slug}.html").read_text()


def _jsonld_url(html: str) -> str:
    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    assert match, "no JSON-LD block emitted"
    return json.loads(match.group(1))["url"]


def _canonical_href(html: str):
    match = re.search(r'<link rel="canonical" href="([^"]*)"', html)
    return match.group(1) if match else None


def test_canonical_falls_back_to_base_url_plus_slug_when_unset(tmp_path):
    post = _Post(slug="docs", canonical_url=None)
    html = _render(tmp_path, post, public_base_url="https://vbwd.cc", home_slug="index")

    assert _jsonld_url(html) == "https://vbwd.cc/docs"
    assert _canonical_href(html) == "https://vbwd.cc/docs"
    # JSON-LD url and the canonical <link> agree.
    assert _jsonld_url(html) == _canonical_href(html)


def test_canonical_home_slug_falls_back_to_root(tmp_path):
    post = _Post(slug="index", title="Home", meta_title="Home", canonical_url=None)
    html = _render(tmp_path, post, public_base_url="https://vbwd.cc", home_slug="index")

    assert _jsonld_url(html) == "https://vbwd.cc/"
    assert _canonical_href(html) == "https://vbwd.cc/"
    assert _jsonld_url(html) == _canonical_href(html)


def test_stored_canonical_url_is_used_verbatim_when_set(tmp_path):
    post = _Post(slug="docs", canonical_url="https://override.example/custom")
    html = _render(tmp_path, post, public_base_url="https://vbwd.cc", home_slug="index")

    assert _jsonld_url(html) == "https://override.example/custom"
    assert _canonical_href(html) == "https://override.example/custom"
    assert _jsonld_url(html) == _canonical_href(html)


def test_canonical_relative_when_no_public_base_url(tmp_path):
    post = _Post(slug="docs", canonical_url=None)
    html = _render(tmp_path, post, public_base_url="", home_slug="index")

    # Root-relative path — a valid canonical, never null/absent.
    assert _jsonld_url(html) == "/docs"
    assert _canonical_href(html) == "/docs"
    assert _jsonld_url(html) == _canonical_href(html)
    assert _jsonld_url(html) is not None
