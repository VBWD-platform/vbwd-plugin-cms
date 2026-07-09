"""Super-header widget seed.

``populate_cms`` seeds the "Super Header" standalone vue-component RECORD so it
appears in the admin picker. An admin then places it themselves — it is
deliberately NOT added to ``_LAYOUT_WIDGET_PLACEMENTS``. Settings ride the
``CmsWidget.config`` JSON; no model or migration change.

These are pure data-shape oracles over ``_STANDALONE_VUE_WIDGETS`` — no DB
needed; the seeder's idempotency is covered by the shared ``_get_or_create_widget``
integration path.

Engineering requirements (binding, restated): TDD-first (RED set); core-agnostic
(CMS plugin only); DRY (reuse the existing 3-layer widget pipeline); no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin.populate_cms import (
    _LAYOUT_WIDGET_PLACEMENTS,
    _STANDALONE_VUE_WIDGETS,
)


def _super_header_entries():
    return [w for w in _STANDALONE_VUE_WIDGETS if w["slug"] == "super-header"]


class TestSuperHeaderSeed:
    def test_exactly_one_super_header_record_is_seeded(self):
        assert len(_super_header_entries()) == 1

    def test_record_is_a_vue_component_resolving_to_SuperHeader(self):
        entry = _super_header_entries()[0]
        assert entry["widget_type"] == "vue-component"
        assert entry["content_json"] == {"component": "SuperHeader"}
        assert entry["name"] == "Super Header"

    def test_config_component_name_and_nav_slug(self):
        config = _super_header_entries()[0]["config"]
        assert config["component_name"] == "SuperHeader"
        assert config["nav_widget_slug"] == "header-nav"

    def test_config_seeds_stickable_defaults(self):
        config = _super_header_entries()[0]["config"]
        assert config["stickable"] is False
        assert config["stickable_offset_px"] == 160

    def test_super_header_is_not_auto_placed_in_a_layout(self):
        placed_widget_slugs = {
            widget_slug
            for placements in _LAYOUT_WIDGET_PLACEMENTS.values()
            for _area, widget_slug in placements
        }
        assert "super-header" not in placed_widget_slugs
