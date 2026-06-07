"""Smoke test: the standalone updater runs end-to-end the way seed/deploy calls it.

Deploy/seed invokes the script as:
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_style_alignment.py
which boils down to ``with create_app().app_context(): main()``. This test
seeds a style, then drives that exact entrypoint (``main`` under an app
context resolving ``db.session``) and asserts the style is aligned.
"""
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services.cms_style_service import CmsStyleService
from plugins.cms.src.services.style_edge_align import EDGE_ALIGN_START_MARKER
from plugins.cms.src.bin import apply_style_alignment


def test_main_entrypoint_aligns_styles(db):
    service = CmsStyleService(CmsStyleRepository(db.session))
    service.create_style(
        {
            "name": "Smoke Style",
            "slug": "smoke-align",
            "source_css": "body { color: teal; }\n",
        }
    )

    # Drive the exact entrypoint deploy/seed runs (the __main__ block calls
    # main() under an app context; the db fixture already supplies one, so
    # main() resolves db.session the same way the script does at runtime).
    apply_style_alignment.main()

    css = CmsStyleService(CmsStyleRepository(db.session)).get_style_css(
        str(CmsStyleRepository(db.session).find_by_slug("smoke-align").id)
    )
    assert css.count(EDGE_ALIGN_START_MARKER) == 1
    assert "body { color: teal; }" in css
