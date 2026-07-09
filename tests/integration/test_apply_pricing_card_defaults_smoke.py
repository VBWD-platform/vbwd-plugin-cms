"""Smoke test: the pricing-card defaults applier runs the way deploy calls it.

Deploy invokes the script as:
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_pricing_card_defaults.py
which boils down to ``with create_app().app_context(): main()``. This test
seeds the two pricing widgets through the repository (no raw SQL), drives the
applier's DB entrypoint, and asserts the defaults are filled non-destructively
and that a second run is a no-op.
"""
from plugins.cms.src.bin import apply_pricing_card_defaults as applier
from plugins.cms.src.bin import populate_cms
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


_OLD_EMBED_HTML = (
    '<section class="embed-guide">\n'
    '  <div id="embed-live-preview"></div>\n'
    '  <script src="/embed/widget.js" data-embed="landing1"'
    ' data-container="embed-live-preview" data-locale="en"'
    ' data-theme="light" data-height="650"></script>\n'
    "</section>\n"
)


def _seed_widgets(session):
    repository = CmsWidgetRepository(session)

    native = CmsWidget(
        slug=applier.NATIVE_PLANS_SLUG,
        name="Pricing — Native CMS Plans",
        widget_type="vue-component",
        content_json={"component": "NativePricingPlans"},
        config={"heading": "Operator Heading"},
        sort_order=0,
        is_active=True,
    )
    repository.save(native)

    content_json, source_css = populate_cms._split_widget_content(_OLD_EMBED_HTML)
    embed = CmsWidget(
        slug=applier.EMBED_GUIDE_SLUG,
        name="Pricing — Embedded Widget Guide",
        widget_type="html",
        content_json=content_json,
        source_css=source_css,
        sort_order=0,
        is_active=True,
    )
    repository.save(embed)


def test_applier_fills_defaults_non_destructively(db):
    _seed_widgets(db.session)

    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["native"] == "updated"
    assert summary["embed"] == "updated"

    repository = CmsWidgetRepository(db.session)
    native = repository.find_by_slug(applier.NATIVE_PLANS_SLUG)
    assert native.config["theme"] == populate_cms.NATIVE_PRICING_CONFIG["theme"]
    assert native.config["highlight_slug"] == "pro"
    assert native.config["features"] == populate_cms.NATIVE_PRICING_FEATURES
    # Operator-set key survives; protected keys never appear.
    assert native.config["heading"] == "Operator Heading"
    assert "subtitle" not in native.config

    embed = repository.find_by_slug(applier.EMBED_GUIDE_SLUG)
    decoded = applier._decode_widget_html(embed.content_json)
    live_tag = applier.find_live_embed_script_tag(decoded)
    assert 'data-highlight="pro"' in live_tag
    assert 'data-theme="indigo"' in live_tag


def test_second_run_is_a_noop(db):
    _seed_widgets(db.session)

    applier.apply_pricing_card_defaults(db.session)
    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["native"] == "already-current"
    assert summary["embed"] == "already-current"


def test_operator_theme_survives_the_applier(db):
    repository = CmsWidgetRepository(db.session)
    repository.save(
        CmsWidget(
            slug=applier.NATIVE_PLANS_SLUG,
            name="Pricing — Native CMS Plans",
            widget_type="vue-component",
            content_json={"component": "NativePricingPlans"},
            config={"theme": "emerald"},
            sort_order=0,
            is_active=True,
        )
    )

    applier.apply_pricing_card_defaults(db.session)

    native = repository.find_by_slug(applier.NATIVE_PLANS_SLUG)
    assert native.config["theme"] == "emerald"
    # The still-empty siblings were filled.
    assert native.config["highlight_slug"] == "pro"


def test_missing_embed_widget_is_skipped_not_created(db):
    # Only seed native; the embed widget is absent → applier must NOT create it.
    repository = CmsWidgetRepository(db.session)
    repository.save(
        CmsWidget(
            slug=applier.NATIVE_PLANS_SLUG,
            name="Pricing — Native CMS Plans",
            widget_type="vue-component",
            content_json={"component": "NativePricingPlans"},
            config={},
            sort_order=0,
            is_active=True,
        )
    )

    summary = applier.apply_pricing_card_defaults(db.session)

    assert summary["embed"] == "absent"
    assert repository.find_by_slug(applier.EMBED_GUIDE_SLUG) is None
