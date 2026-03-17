"""CmsWidgetService — business logic for CMS widgets."""
import re
import json
import zipfile
import io
from typing import List, Dict, Any, Optional
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.cms_menu_item_repository import CmsMenuItemRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.models.cms_widget import CmsWidget, WIDGET_TYPES
from plugins.cms.src.services._slug import unique_slug


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


class CmsWidgetNotFoundError(Exception):
    pass


class CmsWidgetSlugConflictError(Exception):
    pass


class CmsWidgetInUseError(Exception):
    """Raised when trying to delete a widget that is assigned to a layout."""

    pass


class CmsWidgetService:
    def __init__(
        self,
        widget_repo: CmsWidgetRepository,
        menu_item_repo: CmsMenuItemRepository,
        image_repo,
        layout_widget_repo: CmsLayoutWidgetRepository,
    ) -> None:
        self._repo = widget_repo
        self._menu_repo = menu_item_repo
        self._image_repo = image_repo
        self._lw_repo = layout_widget_repo

    def list_widgets(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        result = self._repo.find_all(
            page=params.get("page", 1),
            per_page=min(params.get("per_page", 20), 100),
            sort_by=params.get("sort_by", "sort_order"),
            sort_dir=params.get("sort_dir", "asc"),
            query=params.get("query"),
            widget_type=params.get("widget_type"),
        )
        result["items"] = [self._to_dto(w) for w in result["items"]]
        return result

    def get_widget(self, widget_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(widget_id)
        if not obj:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")
        return self._to_dto(obj, include_menu=True)

    def create_widget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("name is required")
        widget_type = data.get("widget_type", "")
        if widget_type not in WIDGET_TYPES:
            raise ValueError(f"widget_type must be one of {sorted(WIDGET_TYPES)}")
        slug = data.get("slug") or _slugify(name)
        if self._repo.find_by_slug(slug):
            raise CmsWidgetSlugConflictError(f"Slug '{slug}' is already in use")
        obj = self._build(data, slug)
        self._repo.save(obj)
        return self._to_dto(obj)

    def update_widget(self, widget_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        obj = self._repo.find_by_id(widget_id)
        if not obj:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")
        if "slug" in data and data["slug"] != obj.slug:
            if self._repo.find_by_slug(data["slug"]):
                raise CmsWidgetSlugConflictError(
                    f"Slug '{data['slug']}' is already in use"
                )
        for field in (
            "name",
            "slug",
            "content_json",
            "source_css",
            "config",
            "sort_order",
            "is_active",
        ):
            if field in data:
                setattr(obj, field, data[field])
        self._repo.save(obj)
        return self._to_dto(obj)

    def delete_widget(self, widget_id: str) -> None:
        in_use = self._lw_repo.find_by_widget(widget_id)
        if in_use:
            raise CmsWidgetInUseError(
                f"Widget {widget_id} is assigned to {len(in_use)} layout(s)"
            )
        if not self._repo.delete(widget_id):
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")

    def bulk_delete(self, ids: List[str]) -> Dict[str, Any]:
        count = self._repo.bulk_delete(ids)
        return {"deleted": count}

    def replace_menu_tree(
        self, widget_id: str, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        obj = self._repo.find_by_id(widget_id)
        if not obj:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")
        created = self._menu_repo.replace_tree(widget_id, items)
        return [i.to_dict() if hasattr(i, "to_dict") else i for i in created]

    def export_widget(self, widget_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(widget_id)
        if not obj:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")
        data = obj.to_dict()
        if obj.widget_type == "menu":
            items = self._menu_repo.find_tree_by_widget(widget_id)
            data["menu_items"] = [i.to_dict() for i in items]
        return {"type": "cms_widget", "version": 1, "data": data}

    def export_widgets_zip(self, ids: List[str]) -> bytes:
        widgets = self._repo.find_by_ids(ids)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for w in widgets:
                d = w.to_dict()
                if w.widget_type == "menu":
                    items = self._menu_repo.find_tree_by_widget(str(w.id))
                    d["menu_items"] = [i.to_dict() for i in items]
                zf.writestr(f"widgets/{w.slug}.json", json.dumps(d, ensure_ascii=False))
        return buf.getvalue()

    def import_widget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        slug = unique_slug(
            data.get("slug") or _slugify(data.get("name", "imported")),
            lambda s: self._repo.find_by_slug(s) is not None,
        )
        obj = self._build(data, slug)
        self._repo.save(obj)
        if data.get("menu_items") and obj.widget_type == "menu":
            self._menu_repo.replace_tree(str(obj.id), data["menu_items"])
        return self._to_dto(obj)

    # ── private ──────────────────────────────────────────────────────────────

    def _build(self, data: Dict[str, Any], slug: str) -> CmsWidget:
        obj = CmsWidget()
        obj.slug = slug
        obj.name = data.get("name", "").strip()
        obj.widget_type = data.get("widget_type", "html")
        obj.content_json = data.get("content_json")
        obj.source_css = data.get("source_css")
        obj.config = data.get("config")
        obj.sort_order = data.get("sort_order", 0)
        obj.is_active = data.get("is_active", True)
        return obj

    def _to_dto(self, obj: CmsWidget, include_menu: bool = False) -> Dict[str, Any]:
        d = obj.to_dict()
        if include_menu and obj.widget_type == "menu":
            items = self._menu_repo.find_tree_by_widget(str(obj.id))
            d["menu_items"] = [i.to_dict() for i in items]
        return d
