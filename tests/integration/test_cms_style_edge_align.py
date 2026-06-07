"""Integration tests for the edge-alignment updater.

Seeds styles via the service, runs the updater's all-styles pass under an app
context against a real DB, and asserts every style ends with exactly one
EDGE_ALIGN block while its non-marker content is left intact.
"""
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services.cms_style_service import CmsStyleService
from plugins.cms.src.services.style_edge_align import (
    EDGE_ALIGN_START_MARKER,
    EDGE_ALIGN_BLOCK,
)
from plugins.cms.src.bin.apply_style_alignment import (
    apply_alignment_to_all_styles,
)


_NO_INSET_CSS = "body { color: #123456; }\n.brand { font-family: Inter; }\n"
_PRIOR_BLOCK_CSS = (
    ".hero { background: navy; }\n"
    + EDGE_ALIGN_START_MARKER
    + "\n.old-rule { color: lime; }\n"
    + "/* /VBWD_EDGE_ALIGN:v1 */\n"
)


def _seed_style(db, slug, name, css):
    service = CmsStyleService(CmsStyleRepository(db.session))
    return service.create_style({"name": name, "slug": slug, "source_css": css})


class TestEdgeAlignUpdater:
    def test_aligns_style_without_inset_system(self, db):
        _seed_style(db, "align-none", "No Inset", _NO_INSET_CSS)

        apply_alignment_to_all_styles(db.session)

        css = CmsStyleService(CmsStyleRepository(db.session)).get_style_css(
            _slug_id(db, "align-none")
        )
        assert css.count(EDGE_ALIGN_START_MARKER) == 1
        assert EDGE_ALIGN_BLOCK in css
        # Original look CSS preserved verbatim.
        assert "body { color: #123456; }" in css
        assert ".brand { font-family: Inter; }" in css

    def test_replaces_prior_block_no_duplicate(self, db):
        _seed_style(db, "align-prior", "Prior Block", _PRIOR_BLOCK_CSS)

        apply_alignment_to_all_styles(db.session)

        css = CmsStyleService(CmsStyleRepository(db.session)).get_style_css(
            _slug_id(db, "align-prior")
        )
        assert css.count(EDGE_ALIGN_START_MARKER) == 1
        assert ".old-rule { color: lime; }" not in css
        # Non-marker prefix preserved.
        assert ".hero { background: navy; }" in css
        assert ".cms-area--content .container" in css

    def test_idempotent_across_runs(self, db):
        _seed_style(db, "align-idem", "Idempotent", _NO_INSET_CSS)

        first = apply_alignment_to_all_styles(db.session)
        css_after_first = CmsStyleService(CmsStyleRepository(db.session)).get_style_css(
            _slug_id(db, "align-idem")
        )

        second = apply_alignment_to_all_styles(db.session)
        css_after_second = CmsStyleService(
            CmsStyleRepository(db.session)
        ).get_style_css(_slug_id(db, "align-idem"))

        assert css_after_first == css_after_second
        # First pass aligns the style; the second pass leaves it as-is and
        # reports it already-current — proving end-to-end idempotency.
        assert first["updated"] >= 1
        assert second["already_current"] >= 1
        assert css_after_second.count(EDGE_ALIGN_START_MARKER) == 1


def _slug_id(db, slug):
    style = CmsStyleRepository(db.session).find_by_slug(slug)
    assert style is not None, f"style {slug} not seeded"
    return str(style.id)
