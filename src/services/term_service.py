"""TermService — business logic for the unified taxonomy (S47.0)."""
from typing import Any, Dict, List

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services._slug import slugify


class TermNotFoundError(Exception):
    """Raised when a term id does not resolve."""


class TermSlugConflictError(Exception):
    """Raised when (term_type, slug) already exists."""


class UnknownTermTypeError(Exception):
    """Raised when creating a term with an unregistered term_type."""


class TermService:
    """Service for managing taxonomy terms."""

    def __init__(self, repo) -> None:
        self._repo = repo

    def list_terms(self, term_type: str) -> List[Dict[str, Any]]:
        return [term.to_dict() for term in self._repo.find_by_type(term_type)]

    def get_term(self, term_id: str) -> Dict[str, Any]:
        term = self._repo.find_by_id(term_id)
        if not term:
            raise TermNotFoundError(f"Term '{term_id}' not found")
        return term.to_dict()

    def find_or_create(self, term_type: str, name: str) -> Dict[str, Any]:
        """Resolve a term by name within a taxonomy, creating it if absent.

        The slug is derived from the name (same rule ``create_term`` uses), so
        repeated names map to the one term — no duplicates. Single home for
        term resolution, reused by the API content-ingestion path.
        """
        slug = slugify((name or "").strip())
        existing = self._repo.find_by_type_and_slug(term_type, slug)
        if existing:
            return existing.to_dict()
        return self.create_term({"term_type": term_type, "name": name})

    def create_term(self, data: Dict[str, Any]) -> Dict[str, Any]:
        term_type = (data.get("term_type") or "").strip()
        if not term_type_registry.is_registered(term_type):
            raise UnknownTermTypeError(f"Unknown term type '{term_type}'")

        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")

        slug = (data.get("slug") or slugify(name)).strip("/")
        if self._repo.find_by_type_and_slug(term_type, slug):
            raise TermSlugConflictError(
                f"A '{term_type}' term with slug '{slug}' already exists"
            )

        term = CmsTerm()
        term.term_type = term_type
        term.slug = slug
        term.name = name
        term.parent_id = data.get("parent_id")
        term.description = data.get("description")
        term.seo_excluded = data.get("seo_excluded", False)
        term.sort_order = data.get("sort_order", 0)

        self._repo.save(term)
        return term.to_dict()

    def update_term(self, term_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        term = self._repo.find_by_id(term_id)
        if not term:
            raise TermNotFoundError(f"Term '{term_id}' not found")

        if "slug" in data:
            new_slug = (data["slug"] or "").strip("/")
            existing = self._repo.find_by_type_and_slug(term.term_type, new_slug)
            if existing and str(existing.id) != str(term.id):
                raise TermSlugConflictError(
                    f"A '{term.term_type}' term with slug '{new_slug}' already exists"
                )
            term.slug = new_slug

        for field in (
            "name",
            "parent_id",
            "description",
            "seo_excluded",
            "sort_order",
        ):
            if field in data:
                setattr(term, field, data[field])

        self._repo.save(term)
        return term.to_dict()

    def delete_term(self, term_id: str) -> None:
        term = self._repo.find_by_id(term_id)
        if not term:
            raise TermNotFoundError(f"Term '{term_id}' not found")
        self._repo.delete(term_id)

    def bulk_delete(self, ids: List[str]) -> Dict[str, int]:
        return {"deleted": self._repo.bulk_delete(ids)}
