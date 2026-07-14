"""Smoke test: the create-only terms-archive layout applier runs like deploy.

The shared ``terms-archive`` layout (and its route-driven ``TermArchive``
widget) is seeded ONLY by ``populate_cms.py``, which runs on NO production
instance — so on prod ``GET /cms/layouts/by-slug/terms-archive`` 404s and every
category/tag/prefix archive renders degraded. This applier is the safe,
create-only counterpart deploy invokes as::

    docker-compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python plugins/cms/src/bin/apply_terms_archive_layout.py'

which boils down to ``with create_app().app_context(): main()``. These tests
drive the applier against the rolled-back ``db`` fixture and assert: (1) it
creates the layout + widget + archive placement on a DB lacking them; (2) it is
idempotent (a second run creates nothing, no duplicates); (3) it is strictly
non-destructive (an operator-customised layout is left untouched).

Engineering requirements (binding, restated): TDD-first (this RED set precedes
the applier); DevOps-first (clean local + CI from cold start; DB via the
rolled-back ``db`` fixture, no raw SQL); SOLID/DI/DRY (the layout + widget
definition has ONE home, reused from ``populate_cms``); Liskov (create-only is
behaviour-preserving on re-run); clean code; no overengineering (no per-term
page). Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin import apply_terms_archive_layout
from plugins.cms.src.bin.populate_cms import (
    TERMS_ARCHIVE_LAYOUT_SLUG,
    TERMS_ARCHIVE_WIDGET_SLUG,
)
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository


_EXPECTED_AREA_NAMES = {"header", "breadcrumbs", "archive", "footer"}


def test_applier_creates_the_terms_archive_layout_widget_and_placement(db):
    layout_repo = CmsLayoutRepository(db.session)
    assert layout_repo.find_by_slug(TERMS_ARCHIVE_LAYOUT_SLUG) is None

    apply_terms_archive_layout.apply_terms_archive_layout(db.session)

    layout = layout_repo.find_by_slug(TERMS_ARCHIVE_LAYOUT_SLUG)
    assert layout is not None, "terms-archive layout not created"
    assert layout.is_active is True
    assert {area["name"] for area in layout.areas} == _EXPECTED_AREA_NAMES

    widget = (
        db.session.query(CmsWidget)
        .filter_by(slug=TERMS_ARCHIVE_WIDGET_SLUG)
        .one_or_none()
    )
    assert widget is not None, "TermArchive widget not created"
    assert widget.content_json.get("component") == "TermArchive"

    placement = (
        db.session.query(CmsLayoutWidget)
        .filter_by(layout_id=layout.id, widget_id=widget.id)
        .one_or_none()
    )
    assert placement is not None, "TermArchive widget not placed on the layout"
    assert placement.area_name == "archive"


def test_applier_is_idempotent(db):
    apply_terms_archive_layout.apply_terms_archive_layout(db.session)
    apply_terms_archive_layout.apply_terms_archive_layout(db.session)

    layout_count = (
        db.session.query(CmsLayout).filter_by(slug=TERMS_ARCHIVE_LAYOUT_SLUG).count()
    )
    widget_count = (
        db.session.query(CmsWidget).filter_by(slug=TERMS_ARCHIVE_WIDGET_SLUG).count()
    )
    assert layout_count == 1, "terms-archive layout duplicated on re-run"
    assert widget_count == 1, "TermArchive widget duplicated on re-run"

    layout = CmsLayoutRepository(db.session).find_by_slug(TERMS_ARCHIVE_LAYOUT_SLUG)
    archive_placements = (
        db.session.query(CmsLayoutWidget)
        .filter_by(layout_id=layout.id, area_name="archive")
        .count()
    )
    assert archive_placements == 1, "archive placement duplicated on re-run"


def test_applier_is_non_destructive_to_an_existing_layout(db):
    layout_repo = CmsLayoutRepository(db.session)
    sentinel_areas = [{"name": "operator-custom", "label": "Operator", "type": "vue"}]
    layout_repo.save(
        CmsLayout(
            slug=TERMS_ARCHIVE_LAYOUT_SLUG,
            name="Operator Custom Term Archive",
            description="operator sentinel — must not be overwritten",
            areas=sentinel_areas,
            sort_order=99,
        )
    )

    apply_terms_archive_layout.apply_terms_archive_layout(db.session)

    layout = layout_repo.find_by_slug(TERMS_ARCHIVE_LAYOUT_SLUG)
    assert layout.name == "Operator Custom Term Archive"
    assert layout.description == "operator sentinel — must not be overwritten"
    assert layout.areas == sentinel_areas
    assert layout.sort_order == 99


def test_main_entrypoint_creates_the_layout(db):
    apply_terms_archive_layout.main()

    layout = CmsLayoutRepository(db.session).find_by_slug(TERMS_ARCHIVE_LAYOUT_SLUG)
    assert layout is not None
