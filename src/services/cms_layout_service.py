"""CmsLayoutService — business logic for CMS layout templates."""
import re
import json
import zipfile
import io
from typing import List, Dict, Any, Optional
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.models.cms_layout import CmsLayout, AREA_TYPES
from plugins.cms.src.services._slug import unique_slug

_CONTENT_AREA_TYPE = "content"


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _validate_areas(areas: List[Dict[str, Any]]) -> None:
    """Validate area definitions against the fixed catalogue."""
    seen_names = set()
    for area in areas:
        atype = area.get("type", "")
        if atype not in AREA_TYPES:
            raise ValueError(
                f"Unknown area type '{atype}'. Valid types: {sorted(AREA_TYPES)}"
            )
        name = area.get("name", "")
        if name in seen_names:
            raise ValueError(f"duplicate area name '{name}'")
        seen_names.add(name)


class CmsLayoutNotFoundError(Exception):
    pass


class CmsLayoutSlugConflictError(Exception):
    pass


class CmsLayoutService:
    def __init__(
        self,
        layout_repo: CmsLayoutRepository,
        lw_repo: CmsLayoutWidgetRepository,
        widget_repo: CmsWidgetRepository,
        page_repo,
    ) -> None:
        self._repo = layout_repo
        self._lw_repo = lw_repo
        self._widget_repo = widget_repo
        self._page_repo = page_repo

    def list_layouts(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        result = self._repo.find_all(
            page=params.get("page", 1),
            per_page=min(params.get("per_page", 20), 100),
            sort_by=params.get("sort_by", "sort_order"),
            sort_dir=params.get("sort_dir", "asc"),
            query=params.get("query"),
        )
        result["items"] = [self._to_dto(layout) for layout in result["items"]]
        return result

    def get_layout(self, layout_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(layout_id)
        if not obj:
            raise CmsLayoutNotFoundError(f"Layout {layout_id} not found")
        return self._to_dto(obj, include_assignments=True)

    def get_layout_by_slug(self, slug: str) -> Dict[str, Any]:
        obj = self._repo.find_by_slug(slug)
        if not obj:
            raise CmsLayoutNotFoundError(f"Layout '{slug}' not found")
        return self._to_dto(obj, include_assignments=True)

    def create_layout(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("name is required")
        areas = data.get("areas", [])
        _validate_areas(areas)
        slug = data.get("slug") or _slugify(name)
        if self._repo.find_by_slug(slug):
            raise CmsLayoutSlugConflictError(f"Slug '{slug}' is already in use")
        obj = self._build(data, slug)
        self._repo.save(obj)
        return self._to_dto(obj)

    def update_layout(self, layout_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        obj = self._repo.find_by_id(layout_id)
        if not obj:
            raise CmsLayoutNotFoundError(f"Layout {layout_id} not found")
        if "areas" in data:
            _validate_areas(data["areas"])
        if "slug" in data and data["slug"] != obj.slug:
            if self._repo.find_by_slug(data["slug"]):
                raise CmsLayoutSlugConflictError(
                    f"Slug '{data['slug']}' is already in use"
                )
        for field in (
            "name",
            "slug",
            "description",
            "areas",
            "sort_order",
            "is_active",
        ):
            if field in data:
                setattr(obj, field, data[field])
        self._repo.save(obj)
        return self._to_dto(obj)

    def delete_layout(self, layout_id: str) -> None:
        self._lw_repo.delete_by_layout(layout_id)
        if not self._repo.delete(layout_id):
            raise CmsLayoutNotFoundError(f"Layout {layout_id} not found")

    def bulk_delete(self, ids: List[str]) -> Dict[str, Any]:
        for lid in ids:
            self._lw_repo.delete_by_layout(lid)
        count = self._repo.bulk_delete(ids)
        return {"deleted": count}

    def set_widget_assignments(
        self, layout_id: str, assignments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        layout = self._repo.find_by_id(layout_id)
        if not layout:
            raise CmsLayoutNotFoundError(f"Layout {layout_id} not found")

        content_area_names = {
            a["name"]
            for a in (layout.areas or [])
            if a.get("type") == _CONTENT_AREA_TYPE
        }
        for a in assignments:
            if a.get("area_name") in content_area_names:
                raise ValueError(
                    f"area '{a['area_name']}' is a content area and cannot have a widget assigned"
                )

        created = self._lw_repo.replace_for_layout(layout_id, assignments)
        return [lw.to_dict() if hasattr(lw, "to_dict") else lw for lw in created]

    def export_layout(self, layout_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(layout_id)
        if not obj:
            raise CmsLayoutNotFoundError(f"Layout {layout_id} not found")
        assignments = self._lw_repo.find_by_layout(layout_id)
        data = obj.to_dict()
        data["assignments"] = [lw.to_dict() for lw in assignments]
        return {"type": "cms_layout", "version": 1, "data": data}

    def export_layouts_zip(self, ids: List[str]) -> bytes:
        layouts = self._repo.find_by_ids(ids)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for layout in layouts:
                assignments = self._lw_repo.find_by_layout(str(layout.id))
                d = layout.to_dict()
                d["assignments"] = [lw.to_dict() for lw in assignments]
                zf.writestr(f"layouts/{layout.slug}.json", json.dumps(d, ensure_ascii=False))
        return buf.getvalue()

    def import_layout(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data", payload)
        slug = unique_slug(
            data.get("slug") or _slugify(data.get("name", "imported")),
            lambda s: self._repo.find_by_slug(s) is not None,
        )
        areas = data.get("areas", [])
        _validate_areas(areas)
        obj = self._build(data, slug)
        self._repo.save(obj)
        for a in data.get("assignments", []):
            a_copy = dict(a)
            a_copy.pop("id", None)
            a_copy.pop("layout_id", None)
        if data.get("assignments"):
            self._lw_repo.replace_for_layout(
                str(obj.id),
                [
                    {
                        k: v
                        for k, v in a.items()
                        if k in ("area_name", "widget_id", "sort_order")
                    }
                    for a in data["assignments"]
                ],
            )
        return self._to_dto(obj)

    # ── private ──────────────────────────────────────────────────────────────

    def _build(self, data: Dict[str, Any], slug: str) -> CmsLayout:
        obj = CmsLayout()
        obj.slug = slug
        obj.name = data.get("name", "").strip()
        obj.description = data.get("description")
        obj.areas = data.get("areas", [])
        obj.sort_order = data.get("sort_order", 0)
        obj.is_active = data.get("is_active", True)
        return obj

    def _to_dto(
        self, obj: CmsLayout, include_assignments: bool = False
    ) -> Dict[str, Any]:
        d = obj.to_dict()
        if include_assignments:
            assignments = self._lw_repo.find_by_layout(str(obj.id))
            d["assignments"] = [lw.to_dict() for lw in assignments]
        return d
