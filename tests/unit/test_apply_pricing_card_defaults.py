"""Unit tests for the non-destructive pricing-card defaults applier.

The applier fills the seeded pricing-card defaults ONLY where the operator has
not set a value, and upgrades the embed guide's live ``<script>`` tag ONLY while
it still matches the previously-seeded original. It must be strictly
non-destructive and fully idempotent. These tests exercise the pure decision
helpers (no live DB) plus the seeded-constant oracle.

Engineering requirements (binding, restated): TDD-first (these tests were
written before the applier and watched fail); DevOps-first (no DB needed here,
runs cold local + CI); SOLID/DI/DRY (defaults sourced from the single seeder
config, embed tag from the single seeder HTML); Liskov (empty vs operator value
handled by one predicate); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin import apply_pricing_card_defaults as applier
from plugins.cms.src.bin import populate_cms


# Keys the applier must NEVER write.
_PROTECTED_KEYS = ("heading", "subtitle", "cta_label", "highlight_badge", "image_url")


class TestDecideConfigDefaults:
    def test_fills_theme_highlight_and_features_when_unset(self):
        defaults = applier.seed_config_defaults()
        new_config, decisions = applier.decide_config_defaults({}, defaults)

        assert new_config["theme"] == populate_cms.NATIVE_PRICING_CONFIG["theme"]
        assert (
            new_config["highlight_slug"]
            == populate_cms.NATIVE_PRICING_CONFIG["highlight_slug"]
        )
        assert new_config["features"] == populate_cms.NATIVE_PRICING_FEATURES
        assert decisions == {
            "theme": "filled",
            "highlight_slug": "filled",
            "features": "filled",
        }

    def test_fills_empty_string_and_empty_list_values(self):
        defaults = applier.seed_config_defaults()
        starting = {"theme": "", "highlight_slug": None, "features": []}

        new_config, decisions = applier.decide_config_defaults(starting, defaults)

        assert new_config["theme"] == defaults["theme"]
        assert new_config["highlight_slug"] == defaults["highlight_slug"]
        assert new_config["features"] == defaults["features"]
        assert set(decisions.values()) == {"filled"}

    def test_operator_theme_is_never_overwritten(self):
        defaults = applier.seed_config_defaults()
        starting = {"theme": "emerald"}

        new_config, decisions = applier.decide_config_defaults(starting, defaults)

        assert new_config["theme"] == "emerald"
        assert decisions["theme"] == "kept"
        # The still-empty siblings are filled — kept keys don't block filled keys.
        assert decisions["highlight_slug"] == "filled"

    def test_protected_keys_are_never_written(self):
        defaults = applier.seed_config_defaults()
        new_config, _ = applier.decide_config_defaults({}, defaults)

        for key in _PROTECTED_KEYS:
            assert key not in new_config

    def test_operator_protected_keys_are_left_untouched(self):
        defaults = applier.seed_config_defaults()
        starting = {key: f"operator-{key}" for key in _PROTECTED_KEYS}

        new_config, _ = applier.decide_config_defaults(starting, defaults)

        for key in _PROTECTED_KEYS:
            assert new_config[key] == f"operator-{key}"

    def test_second_pass_is_a_noop(self):
        defaults = applier.seed_config_defaults()
        once, _ = applier.decide_config_defaults({}, defaults)

        twice, decisions = applier.decide_config_defaults(once, defaults)

        assert twice == once
        assert set(decisions.values()) == {"kept"}


class TestDecideEmbedUpdate:
    _OLD_HTML = (
        '<div id="embed-live-preview"></div>\n'
        '<script src="/embed/widget.js" data-embed="landing1"'
        ' data-container="embed-live-preview" data-theme="light"></script>'
    )

    def test_upgrades_original_live_tag(self):
        new_html, status = applier.decide_embed_update(self._OLD_HTML)

        assert status == "updated"
        assert new_html is not None
        live_tag = applier.find_live_embed_script_tag(new_html)
        assert 'data-highlight="pro"' in live_tag
        assert 'data-theme="indigo"' in live_tag

    def test_skips_when_live_tag_already_has_highlight(self):
        html = self._OLD_HTML.replace(
            'data-theme="light"', 'data-theme="indigo" data-highlight="pro"'
        )
        new_html, status = applier.decide_embed_update(html)

        assert new_html is None
        assert status in {"already-current", "operator-modified"}

    def test_already_current_after_seeded_update(self):
        # The exact seeded HTML must report already-current (idempotent second run).
        _, status = applier.decide_embed_update(populate_cms.PRICING_EMBED_GUIDE_HTML)
        assert status == "already-current"

    def test_second_pass_on_upgraded_html_is_noop(self):
        once, _ = applier.decide_embed_update(self._OLD_HTML)
        assert once is not None

        new_html, status = applier.decide_embed_update(once)

        assert new_html is None
        assert status == "already-current"

    def test_no_live_script_returns_none(self):
        new_html, status = applier.decide_embed_update("<p>no script here</p>")
        assert new_html is None
        assert status == "no-live-script"


class TestSeededEmbedGuideConstant:
    def test_live_script_tag_advertises_new_attributes(self):
        html = populate_cms.PRICING_EMBED_GUIDE_HTML
        live_tag = applier.find_live_embed_script_tag(html)

        assert live_tag is not None
        assert 'data-theme="indigo"' in live_tag
        assert 'data-highlight="pro"' in live_tag

        match = _extract_features_attr(live_tag)
        assert match is not None
        assert match.split(",") == populate_cms.NATIVE_PRICING_FEATURES

    def test_exactly_one_unescaped_live_script_tag(self):
        html = populate_cms.PRICING_EMBED_GUIDE_HTML
        # The documentation samples are HTML-escaped (&lt;script), so only the
        # single live tag is an unescaped "<script".
        assert html.count("<script") == 1

    def test_features_attribute_placeholder_is_resolved(self):
        # The seeder builds the attr via ",".join(NATIVE_PRICING_FEATURES); the
        # placeholder token must be fully substituted at import time.
        assert "__EMBED_LIVE_FEATURES__" not in populate_cms.PRICING_EMBED_GUIDE_HTML


def _extract_features_attr(tag: str):
    import re

    match = re.search(r'data-features="([^"]*)"', tag)
    return match.group(1) if match else None
