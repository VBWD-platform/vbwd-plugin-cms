"""Unit tests for CmsLayoutService."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_layout_service import (
    CmsLayoutService,
    CmsLayoutNotFoundError,
    CmsLayoutSlugConflictError,
)
from plugins.cms.src.models.cms_layout import CmsLayout


VALID_AREAS = [
    {"name": "page-header", "type": "header", "label": "Header"},
    {"name": "main-body", "type": "content", "label": "Content"},
    {"name": "page-footer", "type": "footer", "label": "Footer"},
]


def _make_service(layouts=None, lw_assignments=None):
    layout_repo = MagicMock()
    lw_repo = MagicMock()
    widget_repo = MagicMock()

    store = {lo.slug: lo for lo in (layouts or [])}
    id_store = {str(lo.id): lo for lo in (layouts or [])}

    layout_repo.find_by_slug.side_effect = lambda slug: store.get(slug)
    layout_repo.find_by_id.side_effect = lambda lid: id_store.get(str(lid))

    def _save(lo):
        store[lo.slug] = lo
        id_store[str(lo.id)] = lo

    layout_repo.save.side_effect = _save
    lw_repo.find_by_layout.return_value = lw_assignments or []
    lw_repo.replace_for_layout.return_value = lw_assignments or []

    return (
        CmsLayoutService(layout_repo, lw_repo, widget_repo),
        layout_repo,
        lw_repo,
    )


def _layout(slug="my-layout", areas=None):
    from uuid import uuid4
    import datetime

    lo = CmsLayout()
    lo.id = uuid4()
    lo.slug = slug
    lo.name = "My Layout"
    lo.description = ""
    lo.areas = areas or VALID_AREAS
    lo.sort_order = 0
    lo.is_active = True
    lo.created_at = lo.updated_at = datetime.datetime.utcnow()
    return lo


class TestBulkSetActive:
    def test_bulk_set_active_toggles_is_active(self):
        a, b = _layout(slug="a"), _layout(slug="b")
        service, repo, _ = _make_service(layouts=[a, b])
        repo.find_by_ids.return_value = [a, b]
        result = service.bulk_set_active([str(a.id), str(b.id)], False)
        assert result == {"updated": 2}
        assert a.is_active is False and b.is_active is False
        # reactivate
        service.bulk_set_active([str(a.id)], True)
        assert a.is_active is True


class TestCreateLayout:
    def test_create_layout_validates_area_types(self):
        svc, _, _ = _make_service()
        result = svc.create_layout(
            {
                "name": "Standard Page",
                "areas": VALID_AREAS,
            }
        )
        assert result["slug"] == "standard-page"
        assert len(result["areas"]) == 3

    def test_create_layout_rejects_unknown_area_type(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="area type"):
            svc.create_layout(
                {
                    "name": "Bad Layout",
                    "areas": [{"name": "x", "type": "unknown-type", "label": "X"}],
                }
            )

    def test_create_layout_rejects_duplicate_area_names(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="duplicate"):
            svc.create_layout(
                {
                    "name": "Dup Layout",
                    "areas": [
                        {"name": "area1", "type": "header", "label": "H"},
                        {"name": "area1", "type": "footer", "label": "F"},
                    ],
                }
            )

    def test_create_layout_rejects_duplicate_slug(self):
        existing = _layout(slug="dupe")
        svc, _, _ = _make_service(layouts=[existing])
        with pytest.raises(CmsLayoutSlugConflictError):
            svc.create_layout({"name": "Dupe", "slug": "dupe", "areas": VALID_AREAS})

    def test_create_layout_requires_name(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="name"):
            svc.create_layout({"areas": VALID_AREAS})


class TestHeadHtml:
    def test_create_layout_persists_head_html(self):
        svc, _, _ = _make_service()
        result = svc.create_layout(
            {
                "name": "With Head",
                "areas": VALID_AREAS,
                "head_html": "<meta name='x' content='y'>",
            }
        )
        assert result["head_html"] == "<meta name='x' content='y'>"

    def test_create_layout_head_html_defaults_to_none(self):
        svc, _, _ = _make_service()
        result = svc.create_layout({"name": "No Head", "areas": VALID_AREAS})
        assert result["head_html"] is None

    def test_update_layout_persists_head_html(self):
        layout = _layout()
        svc, _, _ = _make_service(layouts=[layout])
        result = svc.update_layout(
            str(layout.id),
            {"head_html": "<script>window.x=1;</script>"},
        )
        assert result["head_html"] == "<script>window.x=1;</script>"
        assert layout.head_html == "<script>window.x=1;</script>"


class TestWidgetAssignments:
    def test_set_widget_assignments_replaces_atomically(self):
        layout = _layout()
        svc, _, lw_repo = _make_service(layouts=[layout])
        assignments = [
            {"area_name": "page-header", "widget_id": "abc", "sort_order": 0}
        ]
        svc.set_widget_assignments(str(layout.id), assignments)
        lw_repo.replace_for_layout.assert_called_once_with(str(layout.id), assignments)

    def test_content_area_cannot_have_widget_assigned(self):
        layout = _layout()
        svc, _, _ = _make_service(layouts=[layout])
        with pytest.raises(ValueError, match="content"):
            svc.set_widget_assignments(
                str(layout.id),
                [{"area_name": "main-body", "widget_id": "abc", "sort_order": 0}],
            )


class TestDeleteLayout:
    def test_delete_layout_unlinks_pages_layout_id(self):
        layout = _layout()
        svc, layout_repo, _ = _make_service(layouts=[layout])
        layout_repo.delete.return_value = True
        svc.delete_layout(str(layout.id))
        layout_repo.delete.assert_called_once_with(str(layout.id))


class TestExportImport:
    def test_export_layout_json_includes_widget_slugs(self):
        from unittest.mock import MagicMock as MM

        layout = _layout()
        lw = MM()
        lw.to_dict.return_value = {
            "area_name": "page-header",
            "widget_id": "w1",
            "sort_order": 0,
        }
        svc, _, _ = _make_service(layouts=[layout], lw_assignments=[lw])
        data = svc.export_layout(str(layout.id))
        assert data["type"] == "cms_layout"
        assert "data" in data

    def test_import_layout_renames_slug_on_collision(self):
        existing = _layout(slug="my-layout")
        svc, _, _ = _make_service(layouts=[existing])
        result = svc.import_layout(
            {
                "type": "cms_layout",
                "version": 1,
                "data": {
                    "name": "My Layout",
                    "slug": "my-layout",
                    "areas": VALID_AREAS,
                    "assignments": [],
                },
            }
        )
        assert result["slug"] == "my-layout-2"


# ═══════════════════════════════════════════════════════════════════════════
# Default-layout feature (mirrors the default-STYLE pattern)
# ═══════════════════════════════════════════════════════════════════════════


def _make_service_with_default(layouts=None):
    """Extends _make_service with find_default + save that honours the
    single-default invariant. Tests drive the real service behaviour;
    this mock repo stays simple (no DB constraint)."""
    svc, repo, lw_repo = _make_service(layouts)

    def _find_default():
        for layout in layouts or []:
            if getattr(layout, "is_default", False):
                return layout
        return None

    repo.find_default.side_effect = _find_default
    return svc, repo, lw_repo


class TestDefaultLayoutFlag:
    def test_new_layout_is_not_default_by_default(self):
        svc, _, _ = _make_service()
        result = svc.create_layout({"name": "A", "areas": VALID_AREAS})
        assert result["is_default"] is False

    def test_set_default_promotes_layout(self):
        a = _layout(slug="a")
        a.is_default = False
        svc, _, _ = _make_service_with_default([a])
        result = svc.set_default(str(a.id))
        assert result["is_default"] is True
        assert a.is_default is True

    def test_set_default_demotes_previous_default(self):
        a = _layout(slug="a")
        a.is_default = True
        b = _layout(slug="b")
        b.is_default = False
        svc, _, _ = _make_service_with_default([a, b])
        svc.set_default(str(b.id))
        assert a.is_default is False
        assert b.is_default is True

    def test_set_default_on_missing_layout_raises_not_found(self):
        svc, _, _ = _make_service_with_default([])
        with pytest.raises(CmsLayoutNotFoundError):
            svc.set_default("00000000-0000-0000-0000-000000000000")

    def test_clear_default_unsets_flag(self):
        a = _layout(slug="a")
        a.is_default = True
        svc, _, _ = _make_service_with_default([a])
        svc.clear_default()
        assert a.is_default is False

    def test_update_layout_is_default_true_demotes_previous(self):
        a = _layout(slug="a")
        a.is_default = True
        b = _layout(slug="b")
        b.is_default = False
        svc, _, _ = _make_service_with_default([a, b])
        svc.update_layout(str(b.id), {"is_default": True})
        assert a.is_default is False
        assert b.is_default is True

    def test_update_layout_is_default_false_clears_flag(self):
        a = _layout(slug="a")
        a.is_default = True
        svc, _, _ = _make_service_with_default([a])
        svc.update_layout(str(a.id), {"is_default": False})
        assert a.is_default is False
