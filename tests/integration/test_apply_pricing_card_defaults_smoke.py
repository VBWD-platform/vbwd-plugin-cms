"""Smoke test: the pricing-card defaults applier runs the way deploy calls it.

Deploy invokes the script as:
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_pricing_card_defaults.py
which boils down to ``with create_app().app_context(): main()``. This test
seeds the pricing widgets through the repository (no raw SQL), drives the
applier's DB entrypoint, and asserts the defaults are filled non-destructively
and that a second run is a no-op.

The config pass matches on ``config.component_name`` (NativePricingPlans /
TariffPlanCollection), not on slug — a prod demo widget uses the component name
AS its slug, so slug-matching would miss it. ``highlight_slug`` is filled only
for root-category widgets (the only category with a ``pro`` plan).
"""
from plugins.cms.src.bin import apply_pricing_card_defaults as applier
from plugins.cms.src.bin import populate_cms
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


_NATIVE_PLANS_SLUG = "pricing-native-plans"
_EMBED_GUIDE_SLUG = applier.EMBED_GUIDE_SLUG

_OLD_EMBED_HTML = (
    '<section class="embed-guide">\n'
    '  <div id="embed-live-preview"></div>\n'
    '  <script src="/embed/widget.js" data-embed="landing1"'
    ' data-container="embed-live-preview" data-locale="en"'
    ' data-theme="light" data-height="650"></script>\n'
    "</section>\n"
)


def _save_widget(session, **kwargs):
    CmsWidgetRepository(session).save(CmsWidget(**kwargs))


def _seed_native_and_embed(session):
    _save_widget(
        session,
        slug=_NATIVE_PLANS_SLUG,
        name="Pricing — Native CMS Plans",
        widget_type="vue-component",
        content_json={"component": "NativePricingPlans"},
        config={
            "component_name": "NativePricingPlans",
            "category": "root",
            "heading": "Operator Heading",
        },
        sort_order=0,
        is_active=True,
    )

    content_json, source_css = populate_cms._split_widget_content(_OLD_EMBED_HTML)
    _save_widget(
        session,
        slug=_EMBED_GUIDE_SLUG,
        name="Pricing — Embedded Widget Guide",
        widget_type="html",
        content_json=content_json,
        source_css=source_css,
        sort_order=0,
        is_active=True,
    )


def test_applier_fills_defaults_non_destructively(db):
    _seed_native_and_embed(db.session)

    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["components"][_NATIVE_PLANS_SLUG]["status"] == "updated"
    assert summary["embed"] == "updated"

    repository = CmsWidgetRepository(db.session)
    native = repository.find_by_slug(_NATIVE_PLANS_SLUG)
    assert native.config["theme"] == populate_cms.NATIVE_PRICING_CONFIG["theme"]
    assert native.config["highlight_slug"] == "pro"
    assert native.config["features"] == populate_cms.NATIVE_PRICING_FEATURES
    # Operator-set key survives; protected keys never appear.
    assert native.config["heading"] == "Operator Heading"
    assert "subtitle" not in native.config

    embed = repository.find_by_slug(_EMBED_GUIDE_SLUG)
    decoded = applier._decode_widget_html(embed.content_json)
    live_tag = applier.find_live_embed_script_tag(decoded)
    assert 'data-highlight="pro"' in live_tag
    assert 'data-theme="indigo"' in live_tag


def test_root_tariff_plan_collection_gets_full_styling(db):
    # A prod demo widget whose SLUG is the component name (not the seeder slug).
    _save_widget(
        db.session,
        slug="TariffPlanCollection",
        name="Tariff Plan Collection",
        widget_type="vue-component",
        content_json={"component": "TariffPlanCollection"},
        config={"component_name": "TariffPlanCollection", "category": "root"},
        sort_order=0,
        is_active=True,
    )

    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["components"]["TariffPlanCollection"]["status"] == "updated"
    widget = CmsWidgetRepository(db.session).find_by_slug("TariffPlanCollection")
    assert widget.config["theme"] == "teal"
    assert widget.config["features"] == populate_cms.NATIVE_PRICING_FEATURES
    assert widget.config["highlight_slug"] == "pro"


def test_non_root_tariff_plan_collection_gets_no_highlight(db):
    _save_widget(
        db.session,
        slug="subscription-plans-cards",
        name="Subscription Plans",
        widget_type="vue-component",
        content_json={"component": "TariffPlanCollection"},
        config={
            "component_name": "TariffPlanCollection",
            "category": "subscription-plans",
        },
        sort_order=0,
        is_active=True,
    )

    summary = applier.apply_pricing_card_defaults(db.session)

    filled = summary["components"]["subscription-plans-cards"]["filled"]
    assert "theme" in filled and "features" in filled
    assert "highlight_slug" not in filled
    widget = CmsWidgetRepository(db.session).find_by_slug("subscription-plans-cards")
    assert widget.config["theme"] == "teal"
    assert widget.config["features"] == populate_cms.NATIVE_PRICING_FEATURES
    assert "highlight_slug" not in widget.config


def test_operator_theme_survives_the_applier(db):
    _save_widget(
        db.session,
        slug="pricing-emerald",
        name="Pricing (emerald)",
        widget_type="vue-component",
        content_json={"component": "TariffPlanCollection"},
        config={
            "component_name": "TariffPlanCollection",
            "category": "root",
            "theme": "emerald",
            "heading": "Operator Heading",
            "subtitle": "Operator Subtitle",
            "cta_label": "Buy",
            "highlight_badge": "Best",
            "image_url": "/media/x.png",
        },
        sort_order=0,
        is_active=True,
    )

    applier.apply_pricing_card_defaults(db.session)

    widget = CmsWidgetRepository(db.session).find_by_slug("pricing-emerald")
    assert widget.config["theme"] == "emerald"
    # The still-empty siblings were filled.
    assert widget.config["highlight_slug"] == "pro"
    assert widget.config["features"] == populate_cms.NATIVE_PRICING_FEATURES
    # Protected keys are left exactly as the operator set them.
    assert widget.config["heading"] == "Operator Heading"
    assert widget.config["subtitle"] == "Operator Subtitle"
    assert widget.config["cta_label"] == "Buy"
    assert widget.config["highlight_badge"] == "Best"
    assert widget.config["image_url"] == "/media/x.png"


def test_unrelated_component_widget_is_ignored(db):
    _save_widget(
        db.session,
        slug="super-header",
        name="Super Header",
        widget_type="vue-component",
        content_json={"component": "SuperHeader"},
        config={"component_name": "SuperHeader", "category": "root"},
        sort_order=0,
        is_active=True,
    )

    summary = applier.apply_pricing_card_defaults(db.session)

    assert "super-header" not in summary["components"]
    widget = CmsWidgetRepository(db.session).find_by_slug("super-header")
    assert "theme" not in widget.config
    assert "features" not in widget.config
    assert "highlight_slug" not in widget.config


def test_second_run_is_a_noop(db):
    _seed_native_and_embed(db.session)

    applier.apply_pricing_card_defaults(db.session)
    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["components"][_NATIVE_PLANS_SLUG]["status"] == "already-current"
    assert summary["components"][_NATIVE_PLANS_SLUG]["filled"] == []
    assert summary["embed"] == "already-current"


def test_applier_never_writes_cms_post(db):
    _seed_native_and_embed(db.session)
    posts_before = db.session.query(CmsPost).count()

    applier.apply_pricing_card_defaults(db.session)

    assert db.session.query(CmsPost).count() == posts_before


def test_missing_embed_widget_is_skipped_not_created(db):
    _save_widget(
        db.session,
        slug=_NATIVE_PLANS_SLUG,
        name="Pricing — Native CMS Plans",
        widget_type="vue-component",
        content_json={"component": "NativePricingPlans"},
        config={"component_name": "NativePricingPlans", "category": "root"},
        sort_order=0,
        is_active=True,
    )

    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["embed"] == "absent"
    assert CmsWidgetRepository(db.session).find_by_slug(_EMBED_GUIDE_SLUG) is None
