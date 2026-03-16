"""CmsCategoryService — business logic for CMS categories."""
import re
from typing import List, Dict, Any
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.models.cms_category import CmsCategory


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


class CmsCategoryConflictError(Exception):
    """Raised when deleting a category that still has pages."""


class CmsCategoryService:
    """Service for managing CMS categories."""

    def __init__(self, repo: CmsCategoryRepository) -> None:
        self._repo = repo

    def list_categories(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self._repo.find_all()]

    def get_category(self, category_id: str) -> Dict[str, Any]:
        cat = self._repo.find_by_id(category_id)
        if not cat:
            raise KeyError(f"Category {category_id} not found")
        return cat.to_dict()

    def create_category(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("name is required")

        slug = data.get("slug") or _slugify(name)

        cat = CmsCategory()
        cat.name = name
        cat.slug = slug
        cat.parent_id = data.get("parent_id")
        cat.sort_order = data.get("sort_order", 0)

        self._repo.save(cat)
        return cat.to_dict()

    def update_category(self, category_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        cat = self._repo.find_by_id(category_id)
        if not cat:
            raise KeyError(f"Category {category_id} not found")

        if "name" in data:
            cat.name = data["name"]
        if "slug" in data:
            cat.slug = data["slug"]
        if "parent_id" in data:
            cat.parent_id = data["parent_id"]
        if "sort_order" in data:
            cat.sort_order = data["sort_order"]

        self._repo.save(cat)
        return cat.to_dict()

    def delete_category(self, category_id: str) -> None:
        cat = self._repo.find_by_id(category_id)
        if not cat:
            raise KeyError(f"Category {category_id} not found")

        if cat.pages:
            raise CmsCategoryConflictError(
                f"Category '{cat.slug}' still has {len(cat.pages)} page(s). "
                "Reassign or delete pages first."
            )

        self._repo.delete(category_id)
