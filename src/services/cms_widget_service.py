"""CmsWidgetService — business logic for CMS widgets."""
import re
import json
import zipfile
import io
from typing import List, Dict, Any, Optional, cast
from sqlalchemy.exc import IntegrityError
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.cms_menu_item_repository import CmsMenuItemRepository
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
    """Raised when deleting a widget that is assigned to a layout, page or post."""

    def __init__(self, message: str, usage: Optional[Dict[str, int]] = None) -> None:
        super().__init__(message)
        self.usage: Dict[str, int] = usage or {}


class CmsWidgetService:
    def __init__(
        self,
        widget_repo: CmsWidgetRepository,
        menu_item_repo: CmsMenuItemRepository,
        image_repo,
    ) -> None:
        self._repo = widget_repo
        self._menu_repo = menu_item_repo
        self._image_repo = image_repo

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
        # include_menu so a menu widget in the list carries its items (the
        # per-page widget editor seeds its tree from this list payload).
        result["items"] = [self._to_dto(w, include_menu=True) for w in result["items"]]
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

    def delete_widget(self, widget_id: str, force: bool = False) -> None:
        usage = self._repo.widget_usage(widget_id)
        if any(usage.values()) and not force:
            raise CmsWidgetInUseError(
                self._in_use_message(widget_id, usage), usage=usage
            )
        try:
            deleted = self._repo.delete(widget_id, detach_assignments=force)
        except IntegrityError:
            # Backstop: an assignment created between the usage check and the
            # delete still hits the RESTRICT FK — roll back so the session
            # stays usable and surface the 409-mapped error, never a 500.
            self._repo.rollback()
            raise CmsWidgetInUseError(
                f"Widget {widget_id} is still referenced and cannot be deleted"
            )
        if not deleted:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")

    def bulk_delete(self, ids: List[str], force: bool = False) -> Dict[str, Any]:
        results = [self._delete_for_bulk(widget_id, force) for widget_id in ids]
        deleted_count = sum(1 for entry in results if entry["status"] == "deleted")
        return {"deleted": deleted_count, "results": results}

    def _delete_for_bulk(self, widget_id: str, force: bool) -> Dict[str, Any]:
        """Apply the single-delete guard/force logic to one id, never raising
        for an in-use widget — the bulk caller gets a per-id outcome instead."""
        usage = self._repo.widget_usage(widget_id)
        if any(usage.values()) and not force:
            return {
                "id": widget_id,
                "status": "blocked",
                "reason": self._in_use_message(widget_id, usage),
                "usage": usage,
            }
        try:
            deleted = self._repo.delete(widget_id, detach_assignments=force)
        except IntegrityError:
            self._repo.rollback()
            return {
                "id": widget_id,
                "status": "blocked",
                "reason": f"Widget {widget_id} is still referenced",
            }
        if not deleted:
            return {"id": widget_id, "status": "not_found"}
        return {"id": widget_id, "status": "deleted"}

    @staticmethod
    def _in_use_message(widget_id: str, usage: Dict[str, int]) -> str:
        return (
            f"Widget {widget_id} is in use by {usage['layouts']} layout(s), "
            f"{usage['posts']} post(s)"
        )

    def replace_menu_tree(
        self, widget_id: str, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        obj = self._repo.find_by_id(widget_id)
        if not obj:
            raise CmsWidgetNotFoundError(f"Widget {widget_id} not found")
        created = self._menu_repo.replace_tree(widget_id, items)
        return cast(
            List[Dict[str, Any]],
            [
                menu_item.to_dict() if hasattr(menu_item, "to_dict") else menu_item
                for menu_item in created
            ],
        )

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

    def import_widgets_zip(self, raw: bytes, mode: str = "copy") -> Dict[str, Any]:
        """Import every .json entry inside a zip archive.

        Accepts either flat (`<slug>.json`) or nested (`widgets/<slug>.json`)
        layout — the export zip uses the nested form, loose uploads tend
        to be flat.

        Returns { imported, skipped, failed, items, errors }:
          * imported — number of widgets successfully created or replaced
          * skipped  — non-JSON entries (README, etc.)
          * failed   — JSON entries that could not be imported
          * items    — list of imported widget dicts
          * errors   — list of {file, error} for each failure
        """
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as e:
            raise ValueError(f"Not a valid zip archive: {e}") from e

        imported: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        skipped = 0

        for name in archive.namelist():
            # zip directories end with "/"; ignore those.
            if name.endswith("/"):
                continue
            # macOS `zip` injects AppleDouble resource-fork sidecars under
            # __MACOSX/._*. They carry the original .json extension but
            # contain binary metadata — drop them silently.
            basename = name.rsplit("/", 1)[-1]
            if name.startswith("__MACOSX/") or basename.startswith("._"):
                continue
            if not name.lower().endswith(".json"):
                skipped += 1
                continue
            try:
                data = json.loads(archive.read(name))
                if (
                    isinstance(data, dict)
                    and "data" in data
                    and isinstance(data["data"], dict)
                ):
                    data = data["data"]
                if not isinstance(data, dict):
                    raise ValueError("entry is not a JSON object")
                imported.append(self.import_widget(data, mode=mode))
            except Exception as e:
                errors.append({"file": name, "error": str(e)})

        return {
            "imported": len(imported),
            "skipped": skipped,
            "failed": len(errors),
            "items": imported,
            "errors": errors,
        }

    def import_widget(self, data: Dict[str, Any], mode: str = "copy") -> Dict[str, Any]:
        """Import one widget from a JSON payload.

        mode:
          * "copy"    — if a widget with that slug exists, save as a new
                        row with "-2" / "-3" suffix. Never mutates existing
                        rows. (default, preserves legacy behaviour)
          * "replace" — if a widget with that slug exists, overwrite its
                        fields in place (and re-import its menu tree).
        """
        if mode not in ("copy", "replace"):
            raise ValueError(f"Unknown import mode: {mode!r}")

        requested_slug = data.get("slug") or _slugify(data.get("name", "imported"))

        if mode == "replace":
            existing = self._repo.find_by_slug(requested_slug)
            if existing is not None:
                existing.name = data.get("name", existing.name).strip()
                existing.widget_type = data.get("widget_type", existing.widget_type)
                existing.content_json = data.get("content_json", existing.content_json)
                existing.source_css = data.get("source_css", existing.source_css)
                existing.config = data.get("config", existing.config)
                existing.sort_order = data.get("sort_order", existing.sort_order)
                existing.is_active = data.get("is_active", existing.is_active)
                self._repo.save(existing)
                if data.get("menu_items") and existing.widget_type == "menu":
                    self._menu_repo.replace_tree(str(existing.id), data["menu_items"])
                return self._to_dto(existing)
            slug = requested_slug
        else:
            slug = unique_slug(
                requested_slug,
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
