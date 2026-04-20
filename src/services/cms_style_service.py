"""CmsStyleService — business logic for CMS stylesheets."""
import re
import json
import zipfile
import io
from typing import List, Dict, Any, Optional
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.models.cms_style import CmsStyle
from plugins.cms.src.services._slug import unique_slug


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


class CmsStyleNotFoundError(Exception):
    pass


class CmsStyleSlugConflictError(Exception):
    pass


class CmsStyleService:
    def __init__(self, repo: CmsStyleRepository) -> None:
        self._repo = repo

    def list_styles(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        result = self._repo.find_all(
            page=params.get("page", 1),
            per_page=min(params.get("per_page", 20), 100),
            sort_by=params.get("sort_by", "sort_order"),
            sort_dir=params.get("sort_dir", "asc"),
            query=params.get("query"),
        )
        result["items"] = [s.to_dict() for s in result["items"]]
        return result

    def get_style(self, style_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(style_id)
        if not obj:
            raise CmsStyleNotFoundError(f"Style {style_id} not found")
        return obj.to_dict()

    def get_style_css(self, style_id: str) -> str:
        obj = self._repo.find_by_id(style_id)
        if not obj:
            raise CmsStyleNotFoundError(f"Style {style_id} not found")
        return obj.source_css or ""

    def create_style(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("name is required")
        slug = data.get("slug") or _slugify(name)
        if self._repo.find_by_slug(slug):
            raise CmsStyleSlugConflictError(f"Slug '{slug}' is already in use")
        obj = self._build(data, slug)
        self._repo.save(obj)
        return obj.to_dict()

    def update_style(self, style_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        obj = self._repo.find_by_id(style_id)
        if not obj:
            raise CmsStyleNotFoundError(f"Style {style_id} not found")
        if "slug" in data and data["slug"] != obj.slug:
            if self._repo.find_by_slug(data["slug"]):
                raise CmsStyleSlugConflictError(
                    f"Slug '{data['slug']}' is already in use"
                )
        # Promotions to default must go through set_default to demote any
        # previous default atomically; explicit demotions flow through here.
        if data.get("is_default") is True and not obj.is_default:
            self.set_default(style_id)
            # re-fetch for the remaining field updates below
            obj = self._repo.find_by_id(style_id)
        for field in ("name", "slug", "source_css", "sort_order", "is_active"):
            if field in data:
                setattr(obj, field, data[field])
        if data.get("is_default") is False:
            obj.is_default = False
        self._repo.save(obj)
        return obj.to_dict()

    # ── default-style management ─────────────────────────────────────────────

    def set_default(self, style_id: str) -> Dict[str, Any]:
        """Promote a style to default. Demotes any previous default in the
        same transaction so the single-default invariant holds."""
        target = self._repo.find_by_id(style_id)
        if not target:
            raise CmsStyleNotFoundError(f"Style {style_id} not found")
        previous = self._repo.find_default()
        if previous is not None and str(previous.id) != str(target.id):
            previous.is_default = False
            self._repo.save(previous)
        target.is_default = True
        self._repo.save(target)
        return target.to_dict()

    def clear_default(self) -> None:
        """Unset whichever style is currently default. Idempotent."""
        previous = self._repo.find_default()
        if previous is not None:
            previous.is_default = False
            self._repo.save(previous)

    def get_default_style(self) -> Optional[Dict[str, Any]]:
        """Return the current default style dict, or None if none set."""
        obj = self._repo.find_default()
        return obj.to_dict() if obj else None

    def get_default_style_css(self) -> Optional[str]:
        """Return CSS of the default style if one exists AND is active."""
        obj = self._repo.find_default()
        if obj is None or not obj.is_active:
            return None
        return obj.source_css or ""

    def delete_style(self, style_id: str) -> None:
        if not self._repo.delete(style_id):
            raise CmsStyleNotFoundError(f"Style {style_id} not found")

    def bulk_delete(self, ids: List[str]) -> Dict[str, Any]:
        count = self._repo.bulk_delete(ids)
        return {"deleted": count}

    def export_style(self, style_id: str) -> Dict[str, Any]:
        obj = self._repo.find_by_id(style_id)
        if not obj:
            raise CmsStyleNotFoundError(f"Style {style_id} not found")
        return {"type": "cms_style", "version": 1, "data": obj.to_dict()}

    def export_styles_zip(self, ids: List[str]) -> bytes:
        styles = self._repo.find_by_ids(ids)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in styles:
                zf.writestr(
                    f"styles/{s.slug}.json", json.dumps(s.to_dict(), ensure_ascii=False)
                )
        return buf.getvalue()

    def import_style(self, data: Dict[str, Any]) -> Dict[str, Any]:
        slug = unique_slug(
            data.get("slug") or _slugify(data.get("name", "imported")),
            lambda s: self._repo.find_by_slug(s) is not None,
        )
        obj = self._build(data, slug)
        self._repo.save(obj)
        return obj.to_dict()

    # ── private ──────────────────────────────────────────────────────────────

    def _build(self, data: Dict[str, Any], slug: str) -> CmsStyle:
        obj = CmsStyle()
        obj.slug = slug
        obj.name = data.get("name", "").strip()
        obj.source_css = data.get("source_css", "")
        obj.sort_order = data.get("sort_order", 0)
        obj.is_active = data.get("is_active", True)
        obj.is_default = False
        return obj
