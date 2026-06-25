"""Unit tests for CmsWidgetService."""
import pytest
from unittest.mock import MagicMock
from sqlalchemy.exc import IntegrityError
from plugins.cms.src.services.cms_widget_service import (
    CmsWidgetService,
    CmsWidgetSlugConflictError,
    CmsWidgetInUseError,
)
from plugins.cms.src.models.cms_widget import CmsWidget

NO_USAGE = {"layouts": 0, "posts": 0}


def _make_service(widgets=None, menu_items=None, usage=None):
    widget_repo = MagicMock()
    menu_repo = MagicMock()
    image_repo = MagicMock()

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
    widget_repo.widget_usage.return_value = dict(usage or NO_USAGE)
    widget_repo.delete.side_effect = lambda wid, detach_assignments=False: (
        str(wid) in id_store
    )

    menu_repo.find_tree_by_widget.return_value = menu_items or []
    menu_repo.replace_tree.side_effect = lambda wid, items: items

    return (
        CmsWidgetService(widget_repo, menu_repo, image_repo),
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
        w = _widget()
        svc, _, _ = _make_service(widgets=[w], usage={"layouts": 1, "posts": 0})
        with pytest.raises(CmsWidgetInUseError):
            svc.delete_widget(str(w.id))

    def test_delete_widget_used_in_post_raises_conflict(self):
        """Regression: the old guard checked only layout assignments, so a
        post-assigned widget fell through to a raw IntegrityError (500)."""
        w = _widget()
        svc, _, _ = _make_service(widgets=[w], usage={"layouts": 0, "posts": 1})
        with pytest.raises(CmsWidgetInUseError):
            svc.delete_widget(str(w.id))

    def test_in_use_error_carries_usage_counts(self):
        w = _widget()
        usage = {"layouts": 1, "posts": 3}
        svc, _, _ = _make_service(widgets=[w], usage=usage)
        with pytest.raises(CmsWidgetInUseError) as exc_info:
            svc.delete_widget(str(w.id))
        assert exc_info.value.usage == usage

    def test_delete_widget_not_in_use_succeeds(self):
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w])
        svc.delete_widget(str(w.id))
        repo.delete.assert_called_once_with(str(w.id), detach_assignments=False)

    def test_force_delete_detaches_assignments(self):
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w], usage={"layouts": 1, "posts": 1})
        svc.delete_widget(str(w.id), force=True)
        repo.delete.assert_called_once_with(str(w.id), detach_assignments=True)

    def test_integrity_error_backstop_becomes_in_use_error(self):
        """A racing assignment may slip past the usage check; the delete must
        roll back and surface a 409-mapped error, never a raw 500."""
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w])
        repo.delete.side_effect = IntegrityError("stmt", {}, Exception("fk"))
        with pytest.raises(CmsWidgetInUseError):
            svc.delete_widget(str(w.id))
        repo.rollback.assert_called_once()


class TestBulkDelete:
    def test_bulk_delete_mixed_blocks_used_and_deletes_unused(self):
        used = _widget(slug="used")
        unused = _widget(slug="unused")
        svc, repo, _ = _make_service(widgets=[used, unused])
        usage_by_id = {
            str(used.id): {"layouts": 1, "posts": 0},
            str(unused.id): dict(NO_USAGE),
        }
        repo.widget_usage.side_effect = lambda wid: usage_by_id[str(wid)]

        result = svc.bulk_delete([str(used.id), str(unused.id)])

        assert result["deleted"] == 1
        by_id = {entry["id"]: entry for entry in result["results"]}
        assert by_id[str(used.id)]["status"] == "blocked"
        assert by_id[str(used.id)]["usage"] == usage_by_id[str(used.id)]
        assert by_id[str(unused.id)]["status"] == "deleted"

    def test_bulk_delete_force_deletes_used_widgets(self):
        used = _widget(slug="used")
        svc, repo, _ = _make_service(widgets=[used], usage={"layouts": 1, "posts": 0})
        result = svc.bulk_delete([str(used.id)], force=True)
        assert result["deleted"] == 1
        repo.delete.assert_called_once_with(str(used.id), detach_assignments=True)

    def test_bulk_delete_reports_missing_ids(self):
        svc, _, _ = _make_service()
        result = svc.bulk_delete(["does-not-exist"])
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "not_found"

    def test_bulk_delete_integrity_error_blocks_id_without_raising(self):
        w = _widget()
        svc, repo, _ = _make_service(widgets=[w])
        repo.delete.side_effect = IntegrityError("stmt", {}, Exception("fk"))
        result = svc.bulk_delete([str(w.id)])
        assert result["deleted"] == 0
        assert result["results"][0]["status"] == "blocked"
        repo.rollback.assert_called_once()


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


class TestIsGlobalRemoved:
    """Part 2 — the is_global widget feature is removed entirely.

    The model/to_dict no longer carries is_global, admin create/update ignore
    an is_global in the body (no crash, no persist), and the global-injection
    service method is gone. Engineering requirements (binding, restated):
    TDD-first; no overengineering (the narrowest removal); DRY (one home per
    field). Quality guard: bin/pre-commit-check.sh --plugin cms --full.
    """

    def test_to_dict_has_no_is_global_field(self):
        svc, _, _ = _make_service()
        result = svc.create_widget({"name": "Plain", "widget_type": "html"})
        assert "is_global" not in result

    def test_create_ignores_is_global_in_body(self):
        svc, _, _ = _make_service()
        result = svc.create_widget(
            {"name": "Analytics", "widget_type": "html", "is_global": True}
        )
        assert "is_global" not in result

    def test_update_ignores_is_global_in_body(self):
        widget = _widget()
        svc, _, _ = _make_service(widgets=[widget])
        result = svc.update_widget(str(widget.id), {"is_global": True})
        assert "is_global" not in result
        assert not hasattr(widget, "is_global")

    def test_list_global_widgets_method_is_gone(self):
        svc, _, _ = _make_service()
        assert not hasattr(svc, "list_global_widgets")

    def test_list_widgets_includes_menu_items_for_menu_widgets(self):
        # The per-page widget editor seeds a menu widget's tree from the LIST
        # payload, so list_widgets must attach menu_items for menu widgets.
        menu_widget = _widget(slug="main-menu", widget_type="menu", name="Main Menu")
        item_dict = {"id": "mi-1", "parent_id": None, "label": "Home", "url": "/"}
        menu_item = MagicMock()
        menu_item.to_dict.return_value = item_dict
        svc, widget_repo, _ = _make_service(menu_items=[menu_item])
        widget_repo.find_all.return_value = {
            "items": [menu_widget],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }
        result = svc.list_widgets()
        assert result["items"][0]["menu_items"] == [item_dict]

    def test_list_widgets_omits_menu_items_for_non_menu_widgets(self):
        html_widget = _widget(slug="promo", widget_type="html")
        svc, widget_repo, _ = _make_service(menu_items=[])
        widget_repo.find_all.return_value = {
            "items": [html_widget],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "pages": 1,
        }
        result = svc.list_widgets()
        assert "menu_items" not in result["items"][0]
