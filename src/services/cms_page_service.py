"""CmsPageService — business logic for CMS pages."""
import json
import base64
import re
from typing import List, Dict, Any, Optional
from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.models.cms_page import CmsPage


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


class CmsPageNotFoundError(Exception):
    """Raised when a page is not found or not published."""


class CmsPageSlugConflictError(Exception):
    """Raised when a slug already exists."""


class CmsPageService:
    """Service for managing CMS pages."""

    def __init__(
        self,
        repo: CmsPageRepository,
        category_repo: CmsCategoryRepository,
    ) -> None:
        self._repo = repo
        self._category_repo = category_repo

    def get_page(self, slug: str, published_only: bool = True) -> Dict[str, Any]:
        """Get a page by slug. Raises CmsPageNotFoundError if not found."""
        page = self._repo.find_by_slug(slug)
        if not page:
            raise CmsPageNotFoundError(f"Page '{slug}' not found")
        if published_only and not page.is_published:
            raise CmsPageNotFoundError(f"Page '{slug}' is not published")
        return page.to_dict()

    def list_pages(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "updated_at",
        sort_dir: str = "desc",
        filters: Optional[Dict[str, Any]] = None,
        published_only: bool = False,
    ) -> Dict[str, Any]:
        if published_only:
            category_slug = (filters or {}).get("category_slug")
            result = self._repo.find_published_by_category(
                category_slug=category_slug, page=page, per_page=per_page
            )
        else:
            result = self._repo.find_all(
                page=page,
                per_page=per_page,
                sort_by=sort_by,
                sort_dir=sort_dir,
                filters=filters,
            )
        result["items"] = [p.to_dict() for p in result["items"]]
        return result

    def create_page(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("name is required")

        slug = data.get("slug") or _slugify(name)

        existing = self._repo.find_by_slug(slug)
        if existing:
            raise CmsPageSlugConflictError(f"Slug '{slug}' is already in use")

        page = CmsPage()
        self._apply_data(page, data)
        page.slug = slug
        self._repo.save(page)
        return page.to_dict()

    def update_page(self, page_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        page = self._repo.find_by_id(page_id)
        if not page:
            raise CmsPageNotFoundError(f"Page {page_id} not found")

        if "slug" in data and data["slug"] != page.slug:
            existing = self._repo.find_by_slug(data["slug"])
            if existing:
                raise CmsPageSlugConflictError(
                    f"Slug '{data['slug']}' is already in use"
                )

        self._apply_data(page, data)
        self._repo.save(page)
        return page.to_dict()

    def delete_page(self, page_id: str) -> None:
        if not self._repo.delete(page_id):
            raise CmsPageNotFoundError(f"Page {page_id} not found")

    def bulk_action(
        self,
        ids: List[str],
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        if action == "publish":
            count = self._repo.bulk_publish(ids, True)
        elif action == "unpublish":
            count = self._repo.bulk_publish(ids, False)
        elif action == "delete":
            count = self._repo.bulk_delete(ids)
        elif action == "set_category":
            count = self._repo.bulk_set_category(ids, params.get("category_id"))
        else:
            raise ValueError(f"Unknown bulk action: {action}")
        return {"action": action, "affected": count}

    def export_pages(self, ids: List[str], fmt: str = "json") -> bytes:
        """Export pages as JSON. fmt='json' or 'json_base64' (future: with images)."""
        pages = self._repo.find_by_ids(ids)
        data = [p.to_dict() for p in pages]
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        if fmt == "json_base64":
            return base64.b64encode(payload)
        return payload

    def import_pages(self, raw: bytes) -> Dict[str, Any]:
        """Import pages from JSON export. Skips duplicates."""
        records = json.loads(raw)
        created = 0
        skipped = 0
        for rec in records:
            slug = rec.get("slug")
            if not slug or self._repo.find_by_slug(slug):
                skipped += 1
                continue
            page = CmsPage()
            self._apply_data(page, rec)
            page.slug = slug
            self._repo.save(page)
            created += 1
        return {"created": created, "skipped": skipped}

    # ── private ──────────────────────────────────────────────────────────────

    def _apply_data(self, page: CmsPage, data: Dict[str, Any]) -> None:
        for field in (
            "name",
            "language",
            "content_json",
            "content_html",
            "source_css",
            "category_id",
            "is_published",
            "sort_order",
            "meta_title",
            "meta_description",
            "meta_keywords",
            "og_title",
            "og_description",
            "og_image_url",
            "canonical_url",
            "robots",
            "schema_json",
            "layout_id",
            "style_id",
            "use_theme_switcher_styles",
        ):
            if field in data:
                setattr(page, field, data[field])
