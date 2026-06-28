"""Cookie-consent widget seed (S87).

``populate_cms`` seeds the GDPR/DSGVO Cookie Consent widget as a standalone
vue-component RECORD so it appears in the admin picker. An admin then drops it
into a layout (the widget renders as a body overlay, so the area is irrelevant).
Settings ride the ``CmsWidget.config`` JSON — no model or migration change.

These are pure data-shape oracles over ``_STANDALONE_VUE_WIDGETS`` /
``COOKIE_CONSENT_CONFIG`` — no DB needed; the seeder's idempotency is covered by
the shared ``_get_or_create_widget`` integration path.

Engineering requirements (binding): TDD-first (RED set); core-agnostic (CMS
plugin only); no overengineering (reuse the existing 3-layer widget pipeline).
"""
from plugins.cms.src.bin.populate_cms import (
    COOKIE_CONSENT_CONFIG,
    _STANDALONE_VUE_WIDGETS,
)


def _cookie_entries():
    return [w for w in _STANDALONE_VUE_WIDGETS if w["slug"] == "cookie-consent"]


class TestCookieConsentSeed:
    def test_exactly_one_cookie_consent_record_is_seeded(self):
        assert len(_cookie_entries()) == 1

    def test_record_is_a_vue_component_resolving_to_CookieConsent(self):
        entry = _cookie_entries()[0]
        assert entry["widget_type"] == "vue-component"
        assert entry["content_json"] == {"component": "CookieConsent"}
        assert entry["name"] == "Cookie Consent (GDPR/DSGVO)"

    def test_record_config_is_the_default_cookie_consent_config(self):
        assert _cookie_entries()[0]["config"] is COOKIE_CONSENT_CONFIG

    def test_default_config_has_the_documented_shape(self):
        assert COOKIE_CONSENT_CONFIG["component_name"] == "CookieConsent"
        assert COOKIE_CONSENT_CONFIG["consent_version"] == 1
        assert COOKIE_CONSENT_CONFIG["mode"] == "modal"
        assert COOKIE_CONSENT_CONFIG["privacy_policy_url"] == "/privacy"
        assert COOKIE_CONSENT_CONFIG["show_settings_button"] is True
        assert COOKIE_CONSENT_CONFIG["debug_mode"] is False

    def test_default_config_categories_include_necessary_and_optional_buckets(self):
        categories = COOKIE_CONSENT_CONFIG["categories"]
        assert "necessary" in categories
        for optional in ("statistics", "marketing", "preferences"):
            assert optional in categories
