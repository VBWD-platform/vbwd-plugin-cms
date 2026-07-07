"""Unit tests for the CMS edge-alignment helper.

The helper injects a marker-delimited VBWD_EDGE_ALIGN block into a style's
source_css so the header nav, breadcrumb and main content all start on one
vertical line. It must be idempotent and must only touch the marker block —
never the surrounding (colour / font / look) CSS.
"""
from plugins.cms.src.services.style_edge_align import (
    apply_edge_align,
    EDGE_ALIGN_BLOCK,
    EDGE_ALIGN_START_MARKER,
    EDGE_ALIGN_END_MARKER,
)


PRE_CSS = "body { color: red; }\n.brand { font-family: Inter; }\n"


def _count_blocks(css: str) -> int:
    return css.count(EDGE_ALIGN_START_MARKER)


class TestApplyEdgeAlign:
    def test_appends_block_when_absent(self):
        result = apply_edge_align(PRE_CSS)
        assert EDGE_ALIGN_START_MARKER in result
        assert EDGE_ALIGN_END_MARKER in result
        assert _count_blocks(result) == 1
        # Original CSS preserved verbatim at the front.
        assert result.startswith(PRE_CSS)
        # The canonical block is present.
        assert EDGE_ALIGN_BLOCK in result

    def test_appended_block_has_content_container_selector(self):
        result = apply_edge_align(PRE_CSS)
        assert ".cms-area--content .container" in result

    def test_shared_edge_inset_group_excludes_content_container(self):
        # The shared edge-align group (hero/cta/nav/vue/breadcrumb) must NOT
        # include .cms-area--content .container — that selector gets its own
        # dedicated rule with a fixed 1.5rem gutter, not var(--edge-inset).
        result = apply_edge_align(PRE_CSS)
        block = result.split(EDGE_ALIGN_START_MARKER)[1]
        shared_group_selector = (
            ".cms-area--hero, .cms-area--cta,\n"
            ".cms-widget--header-nav, .cms-widget--footer-nav, "
            ".cms-widget--vue,\n"
            ".cms-breadcrumb {"
        )
        assert shared_group_selector in block
        assert ".cms-breadcrumb, .cms-area--content .container {" not in block

    def test_content_container_uses_fixed_gutter_not_edge_inset(self):
        result = apply_edge_align(PRE_CSS)
        block = result.split(EDGE_ALIGN_START_MARKER)[1]
        content_rule_start = block.index(".cms-area--content .container {")
        content_rule_end = block.index("}", content_rule_start)
        content_rule = block[content_rule_start:content_rule_end]
        assert "padding-left: 1.5rem !important;" in content_rule
        assert "padding-right: 1.5rem !important;" in content_rule
        assert "var(--edge-inset)" not in content_rule
        assert "max-width: var(--container-max, 1200px) !important;" in content_rule

    def test_widget_nav_breadcrumb_rules_still_use_edge_inset(self):
        result = apply_edge_align(PRE_CSS)
        block = result.split(EDGE_ALIGN_START_MARKER)[1]
        shared_group_start = block.index(".cms-area--hero, .cms-area--cta,")
        shared_group_end = block.index("}", shared_group_start)
        shared_group_rule = block[shared_group_start:shared_group_end]
        assert "padding-left: var(--edge-inset) !important;" in shared_group_rule
        assert "padding-right: var(--edge-inset) !important;" in shared_group_rule
        assert (
            ".cms-breadcrumb { gap: 0 !important; "
            "padding-left: var(--edge-inset) !important; }"
        ) in block

    def test_appended_block_flushes_first_header_link(self):
        result = apply_edge_align(PRE_CSS)
        assert (
            ".cms-widget--header-nav .cms-menu > "
            ".cms-menu__item:first-child > .cms-menu__link"
        ) in result

    def test_replaces_existing_block_no_duplicate(self):
        once = apply_edge_align(PRE_CSS)
        # Hand-craft an OLD-looking block (different inner text, same markers)
        old = (
            PRE_CSS
            + "\n"
            + EDGE_ALIGN_START_MARKER
            + "\n.something { color: blue; }\n"
            + EDGE_ALIGN_END_MARKER
            + "\n"
        )
        result = apply_edge_align(old)
        assert _count_blocks(result) == 1
        assert ".something { color: blue; }" not in result
        assert result == once or EDGE_ALIGN_BLOCK in result
        # The non-marker prefix is preserved.
        assert result.startswith(PRE_CSS)

    def test_idempotent(self):
        once = apply_edge_align(PRE_CSS)
        twice = apply_edge_align(once)
        assert once == twice
        assert _count_blocks(twice) == 1

    def test_preserves_css_before_marker(self):
        result = apply_edge_align(PRE_CSS)
        prefix = result.split(EDGE_ALIGN_START_MARKER)[0]
        assert PRE_CSS in prefix
        # No colour rule was mutated.
        assert "body { color: red; }" in result
        assert ".brand { font-family: Inter; }" in result

    def test_replace_preserves_css_after_marker(self):
        # CSS may have trailing content after an old block; replacement must
        # keep the prefix and not corrupt unrelated content.
        old = (
            PRE_CSS
            + "\n"
            + EDGE_ALIGN_START_MARKER
            + "\n.legacy {}\n"
            + EDGE_ALIGN_END_MARKER
        )
        result = apply_edge_align(old)
        assert _count_blocks(result) == 1
        assert "body { color: red; }" in result

    def test_handles_empty_source_css(self):
        result = apply_edge_align("")
        assert _count_blocks(result) == 1
        assert EDGE_ALIGN_BLOCK in result

    def test_handles_none_source_css(self):
        result = apply_edge_align(None)
        assert _count_blocks(result) == 1
        assert EDGE_ALIGN_BLOCK in result

    def test_no_root_edge_inset_override_in_block(self):
        # The block must NOT introduce a top-level :root{--edge-inset} default,
        # which would override fullwidth themes' 1.5rem. Only the media query
        # at the bottom may set it.
        result = apply_edge_align("")
        block = result.split(EDGE_ALIGN_START_MARKER)[1]
        # The only :root in the block is inside the max-width:700px media query.
        assert "@media (max-width: 700px) { :root { --edge-inset: 1rem; } }" in block
        # No bare top-level ":root" rule that DEFINES --edge-inset outside the
        # media query (var(--edge-inset) *reads* are fine; only :root *writes*
        # would override fullwidth's 1.5rem).
        before_media = block.split("@media")[0]
        assert ":root" not in before_media
