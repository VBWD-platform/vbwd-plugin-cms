"""Unit guards for the public "Embedded Pricing" guide page body.

The guide (constant ``PRICING_EMBED_GUIDE_HTML`` in ``populate_cms``, mirrored
into the ``docs/imports/pages/pricing-embedded.json`` import artifact) documents
the ``/embed/widget.js`` loader for third-party sites. The loader's real
attribute set is: ``data-embed, data-category, data-container, data-locale,
data-theme, data-height, data-highlight, data-image, data-features,
data-heading, data-subtitle, data-cta, data-badge``. ``data-plans`` never
existed — plan-slug filtering is a CMS-widget config key (``plan_slugs``), not an
embed attribute — so it must not appear in the public guide.

These tests read the REAL constant AND the REAL fixture the seeder reads (via
``_load_pages``) so the documentation cannot silently drift back to the phantom
attribute or the stale ``light``/``dark``-only theme set.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI, no DB needed here); SOLID/DI/DRY (one source of truth for the
attribute list); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re

from plugins.cms.src.bin import populate_cms

# The seven presentation attributes added on top of the original loader set.
NEW_EMBED_ATTRIBUTES = (
    "data-highlight",
    "data-image",
    "data-features",
    "data-heading",
    "data-subtitle",
    "data-cta",
    "data-badge",
)

# ALLOWED_THEMES in EmbedLanding1View / Landing1View — anything else silently
# falls back to 'default', so the guide must advertise exactly these six.
ALLOWED_THEMES = ("default", "light", "dark", "teal", "indigo", "emerald")


def _live_preview_script(content_html: str) -> str:
    """Return the single real ``<script>`` element whose ``data-container`` is
    the live preview. The copy-paste code samples HTML-escape their tags
    (``&lt;script``) so only the live embed is a real ``<script`` element.
    """
    real_scripts = re.findall(r"<script\b[^>]*>.*?</script>", content_html, re.DOTALL)
    live = [tag for tag in real_scripts if 'data-container="embed-live-preview"' in tag]
    assert len(live) == 1, f"expected exactly one live-preview script, got {len(live)}"
    return live[0]


def _assert_guide_is_correct(content_html: str) -> None:
    """Shared oracle applied to both the Python constant and the JSON fixture."""
    # 1 — the phantom attribute must be gone everywhere.
    assert "data-plans" not in content_html, "phantom data-plans attribute present"

    # 2 — every one of the seven new attributes is documented.
    for attribute in NEW_EMBED_ATTRIBUTES:
        assert attribute in content_html, f"{attribute} not documented in the guide"

    # 3 — all six allowed theme values are named.
    for theme in ALLOWED_THEMES:
        assert (
            re.search(rf"\b{re.escape(theme)}\b", content_html) is not None
        ), f"allowed theme '{theme}' not mentioned in the guide"

    # 4 — exactly one live embed script; its feature placeholder is resolved.
    _live_preview_script(content_html)
    assert (
        "__EMBED_LIVE_FEATURES__" not in content_html
    ), "unresolved __EMBED_LIVE_FEATURES__ placeholder remains in the guide"


class TestPricingEmbedGuideConstant:
    """The in-code constant is the primary source the seeder writes for fresh
    installs (``pricing-embed-demo`` html widget + ``pricing-embedded`` page)."""

    def test_guide_documents_current_embed_contract(self):
        _assert_guide_is_correct(populate_cms.PRICING_EMBED_GUIDE_HTML)

    def test_live_features_resolve_to_native_pricing_bullets(self):
        script = _live_preview_script(populate_cms.PRICING_EMBED_GUIDE_HTML)
        match = re.search(r'data-features="([^"]*)"', script)
        assert match is not None
        assert match.group(1).split(",") == populate_cms.NATIVE_PRICING_FEATURES


class TestPricingEmbeddedImportArtifact:
    """The ``pricing-embedded.json`` import artifact must not drift from the
    constant — it is parsed exactly the way ``_load_pages`` reads it."""

    def _content_html(self) -> str:
        pages = {page["slug"]: page for page in populate_cms._load_pages()}
        assert "pricing-embedded" in pages, "pricing-embedded page not seeded"
        return pages["pricing-embedded"]["content_html"]

    def test_import_artifact_documents_current_embed_contract(self):
        _assert_guide_is_correct(self._content_html())
