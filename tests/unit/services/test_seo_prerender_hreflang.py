"""S152 W3b — prerender hreflang derives sibling URLs with the shared rule.

A translation sibling without a stored ``canonical_url`` used to be DROPPED from
the prerender ``<link rel="alternate" hreflang>`` set, while the sitemap
alternates and the public ``translations`` payload derived
``<public_base_url>/<slug>`` for it. The prerender now applies the same
``derive_canonical_url`` rule, so all three lists agree.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (pure unit, no DB); SOLID/DI/DRY (ONE canonical rule —
``derive_canonical_url`` — for self and siblings); Liskov (a sibling with an
explicit ``canonical_url`` renders verbatim, as before); clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re

from plugins.cms.src.services.seo_post_loader import _Sibling
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.tests.unit.services.test_seo_prerender import _Post, _event

PUBLIC_BASE_URL = "https://site.example"
HREFLANG_PATTERN = re.compile(
    r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"'
)


class _SiblingLoader:
    """Test double: returns one post with a fixed sibling list."""

    def __init__(self, post, siblings):
        self._post = post
        self._siblings = siblings

    def load(self, post_id):
        return self._post, [], self._siblings


def _prerender_alternates(tmp_path, post, siblings):
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_SiblingLoader(post, siblings),
        public_base_url=PUBLIC_BASE_URL,
    )
    writer.handle_content_changed(_event(post))
    html = (tmp_path / "seo" / f"{post.slug}.html").read_text()
    return HREFLANG_PATTERN.findall(html)


def test_sibling_without_canonical_url_gets_the_derived_url(tmp_path):
    post = _Post(slug="pricing", canonical_url="https://site.example/pricing")
    siblings = [_Sibling("de", None, "preise")]

    alternates = _prerender_alternates(tmp_path, post, siblings)

    assert alternates == [
        ("en", "https://site.example/pricing"),
        ("de", "https://site.example/preise"),
        ("x-default", "https://site.example/pricing"),
    ]


def test_sibling_with_explicit_canonical_url_is_unchanged(tmp_path):
    post = _Post(slug="pricing", canonical_url="https://site.example/pricing")
    siblings = [_Sibling("de", "https://other.example/de/preise", "preise")]

    alternates = _prerender_alternates(tmp_path, post, siblings)

    assert ("de", "https://other.example/de/preise") in alternates


def test_post_without_siblings_keeps_self_and_x_default_only(tmp_path):
    post = _Post(slug="pricing", canonical_url=None)

    alternates = _prerender_alternates(tmp_path, post, [])

    assert alternates == [
        ("en", "https://site.example/pricing"),
        ("x-default", "https://site.example/pricing"),
    ]
