"""Integration tests for the super-header applier.

The production applier ``apply_super_header.py`` installs the ``super-header``
CMS widget onto an EXISTING database (deploy runs the destructive
``populate_cms.py`` seeders on no instance, so the newly-seeded widget never
reaches an already-provisioned DB). These tests seed layouts/widgets through the
repositories/services (no raw SQL), then drive the applier and assert:

  * dry-run on a DB without super-header reports "would create", emits the
    rollback JSON, and writes NOTHING;
  * ``--apply`` creates the widget, repoints a layout's ``header`` area, and
    leaves that layout's other areas (widget_id + sort_order) untouched, and a
    layout without a header area untouched;
  * ``--apply`` when the widget already exists with a customised config leaves
    that config alone;
  * a second ``--apply`` run is idempotent (already-current, no further writes);
  * the emitted rollback JSON round-trips — feeding it back restores the
    original header widget_id.

Engineering requirements (binding, restated): TDD-first (these RED tests gate
the applier); DevOps-first (clean local + CI from cold start, self-cleaning
rollback-isolated ``db`` fixture, no TRUNCATE); SOLID/DI/DRY (seed via the same
services/repos the app uses; the applier reads the single seed source of truth);
Liskov; clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import json

from plugins.cms.src.bin import apply_super_header as applier
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository


def _make_widget(session, slug, name, config=None):
    repository = CmsWidgetRepository(session)
    widget = CmsWidget(
        slug=slug,
        name=name,
        widget_type="vue-component",
        content_json={"component": name},
        config=config or {},
        sort_order=0,
        is_active=True,
    )
    repository.save(widget)
    return widget


def _make_layout(session, slug, assignments):
    layout_repo = CmsLayoutRepository(session)
    lw_repo = CmsLayoutWidgetRepository(session)
    from plugins.cms.src.models.cms_layout import CmsLayout

    layout = CmsLayout()
    layout.slug = slug
    layout.name = slug
    layout.areas = [
        {"name": assignment["area_name"], "type": "hero"} for assignment in assignments
    ]
    layout_repo.save(layout)
    if assignments:
        lw_repo.replace_for_layout(str(layout.id), assignments)
    return layout


def _read_rollback_line(capsys):
    captured = capsys.readouterr()
    lines = [
        line
        for line in captured.out.splitlines()
        if line.startswith(applier.ROLLBACK_LINE_PREFIX)
    ]
    assert len(lines) == 1, f"expected exactly one rollback line, got: {lines}"
    return json.loads(lines[0][len(applier.ROLLBACK_LINE_PREFIX) :])


def test_dry_run_reports_would_create_and_writes_nothing(db, capsys):
    header_widget = _make_widget(db.session, "header-nav", "HeaderNav")
    footer_widget = _make_widget(db.session, "footer-nav", "FooterNav")
    _make_layout(
        db.session,
        "content-page",
        [
            {
                "area_name": "header",
                "widget_id": str(header_widget.id),
                "sort_order": 0,
            },
            {
                "area_name": "footer",
                "widget_id": str(footer_widget.id),
                "sort_order": 1,
            },
        ],
    )

    summary = applier.apply_super_header(db.session, apply_changes=False)

    assert summary["widget"] == "would-create"
    assert summary["repointed"] == 1
    assert summary["applied"] is False

    rollback = _read_rollback_line(capsys)
    assert "content-page" in rollback
    assert rollback["content-page"]["assignments"][0]["widget_id"] == str(
        header_widget.id
    )

    # Nothing was written: widget still absent, header assignment unchanged.
    widget_repo = CmsWidgetRepository(db.session)
    assert widget_repo.find_by_slug(applier.SUPER_HEADER_SLUG) is None
    lw_repo = CmsLayoutWidgetRepository(db.session)
    layout = CmsLayoutRepository(db.session).find_by_slug("content-page")
    assignments = lw_repo.find_by_layout(str(layout.id))
    header = next(a for a in assignments if a.area_name == "header")
    assert str(header.widget_id) == str(header_widget.id)


def test_apply_creates_widget_and_repoints_header_only(db, capsys):
    header_widget = _make_widget(db.session, "header-nav", "HeaderNav")
    footer_widget = _make_widget(db.session, "footer-nav", "FooterNav")
    _make_layout(
        db.session,
        "content-page",
        [
            {
                "area_name": "header",
                "widget_id": str(header_widget.id),
                "sort_order": 0,
            },
            {
                "area_name": "footer",
                "widget_id": str(footer_widget.id),
                "sort_order": 7,
            },
        ],
    )
    _make_layout(
        db.session,
        "no-header-layout",
        [
            {
                "area_name": "footer",
                "widget_id": str(footer_widget.id),
                "sort_order": 0,
            },
        ],
    )

    summary = applier.apply_super_header(db.session, apply_changes=True)

    assert summary["widget"] == "created"
    assert summary["repointed"] == 1
    # At least the layout we seeded with no header area is reported; the shared
    # test DB may carry other header-less baseline layouts too.
    assert summary["no_header"] >= 1
    assert summary["applied"] is True

    widget_repo = CmsWidgetRepository(db.session)
    super_header = widget_repo.find_by_slug(applier.SUPER_HEADER_SLUG)
    assert super_header is not None
    # Config mirrors the canonical seed entry exactly.
    seed = applier._load_super_header_seed()
    assert super_header.config == seed["config"]

    lw_repo = CmsLayoutWidgetRepository(db.session)
    layout = CmsLayoutRepository(db.session).find_by_slug("content-page")
    assignments = {a.area_name: a for a in lw_repo.find_by_layout(str(layout.id))}
    assert str(assignments["header"].widget_id) == str(super_header.id)
    # Non-header area preserved exactly.
    assert str(assignments["footer"].widget_id) == str(footer_widget.id)
    assert assignments["footer"].sort_order == 7

    # Layout with no header area is untouched.
    no_header = CmsLayoutRepository(db.session).find_by_slug("no-header-layout")
    no_header_assignments = lw_repo.find_by_layout(str(no_header.id))
    assert len(no_header_assignments) == 1
    assert str(no_header_assignments[0].widget_id) == str(footer_widget.id)


def test_apply_leaves_existing_customised_config_untouched(db, capsys):
    custom_config = {"component_name": "SuperHeader", "logo_text": "OperatorBrand"}
    _make_widget(
        db.session,
        applier.SUPER_HEADER_SLUG,
        "Super Header",
        config=custom_config,
    )

    summary = applier.apply_super_header(db.session, apply_changes=True)

    assert summary["widget"] == "already-present"
    widget_repo = CmsWidgetRepository(db.session)
    super_header = widget_repo.find_by_slug(applier.SUPER_HEADER_SLUG)
    assert super_header.config == custom_config


def test_second_apply_run_is_idempotent(db, capsys):
    header_widget = _make_widget(db.session, "header-nav", "HeaderNav")
    _make_layout(
        db.session,
        "content-page",
        [
            {
                "area_name": "header",
                "widget_id": str(header_widget.id),
                "sort_order": 0,
            },
        ],
    )

    applier.apply_super_header(db.session, apply_changes=True)
    capsys.readouterr()  # drain first run's rollback line

    summary = applier.apply_super_header(db.session, apply_changes=True)

    assert summary["widget"] == "already-present"
    assert summary["repointed"] == 0
    assert summary["already_current"] == 1

    rollback = _read_rollback_line(capsys)
    assert rollback == {}  # nothing affected on the idempotent run


def test_rollback_json_round_trips(db, capsys):
    header_widget = _make_widget(db.session, "header-nav", "HeaderNav")
    _make_layout(
        db.session,
        "content-page",
        [
            {
                "area_name": "header",
                "widget_id": str(header_widget.id),
                "sort_order": 0,
            },
        ],
    )

    applier.apply_super_header(db.session, apply_changes=True)
    rollback = _read_rollback_line(capsys)

    lw_repo = CmsLayoutWidgetRepository(db.session)
    layout_repo = CmsLayoutRepository(db.session)
    layout = layout_repo.find_by_slug("content-page")
    # After apply the header points at super-header, not the original.
    super_header = CmsWidgetRepository(db.session).find_by_slug(
        applier.SUPER_HEADER_SLUG
    )
    current = lw_repo.find_by_layout(str(layout.id))
    assert str(current[0].widget_id) == str(super_header.id)

    # Feed the rollback record back to restore the original header widget_id.
    record = rollback["content-page"]
    lw_repo.replace_for_layout(record["layout_id"], record["assignments"])

    restored = lw_repo.find_by_layout(str(layout.id))
    header = next(a for a in restored if a.area_name == "header")
    assert str(header.widget_id) == str(header_widget.id)
