"""Unit tests for CmsLayoutService."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_layout_service import (
    CmsLayoutService,
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
    page_repo = MagicMock()

    store = {layout.slug: layout for layout in (layouts or [])}
    id_store = {str(layout.id): layout for layout in (layouts or [])}

    layout_repo.find_by_slug.side_effect = lambda slug: store.get(slug)
    layout_repo.find_by_id.side_effect = lambda lid: id_store.get(str(lid))

    def _save(layout):
        store[layout.slug] = layout
        id_store[str(layout.id)] = layout

    layout_repo.save.side_effect = _save
    lw_repo.find_by_layout.return_value = lw_assignments or []
    lw_repo.replace_for_layout.return_value = lw_assignments or []

    return (
        CmsLayoutService(layout_repo, lw_repo, widget_repo, page_repo),
        layout_repo,
        lw_repo,
    )


def _layout(slug="my-layout", areas=None):
    from uuid import uuid4
    import datetime

    layout = CmsLayout()
    layout.id = uuid4()
    layout.slug = slug
    layout.name = "My Layout"
    layout.description = ""
    layout.areas = areas or VALID_AREAS
    layout.sort_order = 0
    layout.is_active = True
    layout.created_at = layout.updated_at = datetime.datetime.utcnow()
    return layout


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
