"""Unit tests for CmsWidgetService."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_widget_service import (
    CmsWidgetService,
    CmsWidgetSlugConflictError,
    CmsWidgetInUseError,
)
from plugins.cms.src.models.cms_widget import CmsWidget


def _make_service(widgets=None, menu_items=None, layout_widgets=None):
    widget_repo = MagicMock()
    menu_repo = MagicMock()
    image_repo = MagicMock()
    lw_repo = MagicMock()

    store = {w.slug: w for w in (widgets or [])}
    id_store = {str(w.id): w for w in (widgets or [])}

    widget_repo.find_by_slug.side_effect = lambda slug: store.get(slug)
    widget_repo.find_by_id.side_effect = lambda wid: id_store.get(str(wid))

    def _save(w):
        store[w.slug] = w
        id_store[str(w.id)] = w

    widget_repo.save.side_effect = _save
    widget_repo.find_by_ids.side_effect = lambda ids: [
        id_store[i] for i in ids if i in id_store
    ]

    menu_repo.find_tree_by_widget.return_value = menu_items or []
    menu_repo.replace_tree.side_effect = lambda wid, items: items

    lw_repo.find_by_widget.return_value = layout_widgets or []

    return (
        CmsWidgetService(widget_repo, menu_repo, image_repo, lw_repo),
        widget_repo,
        menu_repo,
    )


def _widget(slug="my-widget", widget_type="html", name="My Widget"):
    from uuid import uuid4
    import datetime

    w = CmsWidget()
    w.id = uuid4()
    w.slug = slug
    w.name = name
    w.widget_type = widget_type
    w.content_json = {"content": ""}
    w.source_css = ""
    w.config = None
    w.sort_order = 0
    w.is_active = True
    w.created_at = w.updated_at = datetime.datetime.utcnow()
    return w


class TestCreateWidget:
    def test_create_widget_html_stores_content_json_and_source_css(self):
        svc, repo, _ = _make_service()
        b64 = "PHA+aGVsbG88L3A+"  # base64("<p>hello</p>")
        content = {"content": b64}
        result = svc.create_widget(
            {
                "name": "Header Widget",
                "widget_type": "html",
                "content_json": content,
                "source_css": ".hero { color: red; }",
            }
        )
        assert result["content_json"] == content
        assert result["source_css"] == ".hero { color: red; }"
        repo.save.assert_called_once()

    def test_create_widget_rejects_unknown_type(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="widget_type"):
            svc.create_widget({"name": "Bad", "widget_type": "unknown"})

    def test_create_widget_requires_name(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="name"):
            svc.create_widget({"widget_type": "html"})

    def test_create_widget_rejects_duplicate_slug(self):
        existing = _widget(slug="dupe")
        svc, _, _ = _make_service(widgets=[existing])
        with pytest.raises(CmsWidgetSlugConflictError):
            svc.create_widget({"name": "Dupe", "slug": "dupe", "widget_type": "html"})


class TestUpdateWidget:
    def test_update_widget_html_syncs_content_json_and_source_css(self):
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w])
        b64_html = "PHAgY2xhc3M9InRlc3QiPnVwZGF0ZWQ8L3A+"  # base64("<p class="test">updated</p>")
        result = svc.update_widget(
            str(w.id),
            {
                "content_json": {"content": b64_html},
                "source_css": ".test { color: red; }",
            },
        )
        assert result["content_json"] == {"content": b64_html}
        assert result["source_css"] == ".test { color: red; }"
        repo.save.assert_called()


class TestDeleteWidget:
    def test_delete_widget_used_in_layout_raises_conflict(self):
        from unittest.mock import MagicMock as MM

        w = _widget()
        svc, _, _ = _make_service(widgets=[w], layout_widgets=[MM()])
        with pytest.raises(CmsWidgetInUseError):
            svc.delete_widget(str(w.id))

    def test_delete_widget_not_in_use_succeeds(self):
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w], layout_widgets=[])
        svc.delete_widget(str(w.id))
        repo.delete.assert_called_once_with(str(w.id))


class TestMenuTree:
    def test_replace_menu_tree_atomically(self):
        w = _widget(widget_type="menu")
        svc, _, menu_repo = _make_service(widgets=[w])
        items = [{"label": "Home", "url": "/", "sort_order": 0}]
        svc.replace_menu_tree(str(w.id), items)
        menu_repo.replace_tree.assert_called_once_with(str(w.id), items)


class TestImportWidget:
    def test_import_widget_renames_slug_on_collision(self):
        existing = _widget(slug="my-widget")
        svc, _, _ = _make_service(widgets=[existing])
        result = svc.import_widget(
            {
                "name": "My Widget",
                "slug": "my-widget",
                "widget_type": "html",
                "content_json": {},
                "content_html": "",
            }
        )
        assert result["slug"] == "my-widget-2"

    def test_import_widget_uses_original_slug_when_no_collision(self):
        svc, _, _ = _make_service()
        result = svc.import_widget(
            {
                "name": "Fresh",
                "slug": "fresh-widget",
                "widget_type": "html",
                "content_json": {},
                "content_html": "",
            }
        )
        assert result["slug"] == "fresh-widget"
