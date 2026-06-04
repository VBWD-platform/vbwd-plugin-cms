"""TermImportExportService — VBWD-standard taxonomy export/import.

Round-trips the unified taxonomy (categories + tags + plugin term-types) as a
portable JSON envelope so the fe-admin Taxonomy page can back up / restore /
move terms between environments. The envelope intentionally carries the
**natural key** ``(term_type, slug)`` and a ``parent_slug`` reference instead of
internal UUIDs, so an import re-resolves identity on the target DB.

Upsert is by ``(term_type, slug)``; ``parent_slug`` is resolved within the same
``term_type`` via a two-pass walk (every row is created/updated first, then
parents are linked) so item order in the payload does not matter. Idempotent: a
re-import of the same payload creates nothing new.

Single responsibility: only export/import. Term CRUD stays in ``TermService``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services import term_type_registry
from plugins.cms.src.services._slug import slugify

ENVELOPE_VERSION = 1
ENVELOPE_ENTITY = "cms_term"

# The portable, id-free fields of a term (the natural key + content).
_EXPORT_FIELDS = (
    "term_type",
    "slug",
    "name",
    "description",
    "seo_excluded",
    "sort_order",
)


class TermImportError(Exception):
    """Raised when an import payload is malformed or references unknown data."""


class TermImportExportService:
    """Export / import taxonomy terms as a VBWD-standard JSON envelope."""

    def __init__(self, repo) -> None:
        self._repo = repo

    # ── export ───────────────────────────────────────────────────────────────

    def export_terms(self, term_type: Optional[str] = None) -> Dict[str, Any]:
        """Return the VBWD-standard envelope for all terms (or one type).

        ``parent_slug`` is the parent term's slug (parents are always within the
        same ``term_type``), or ``None`` for a root / flat term.
        """
        terms = (
            self._repo.find_by_type(term_type) if term_type else self._repo.find_all()
        )
        slug_by_id = {str(term.id): term.slug for term in terms}
        return {
            "version": ENVELOPE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entity": ENVELOPE_ENTITY,
            "items": [self._to_item(term, slug_by_id) for term in terms],
        }

    def _to_item(self, term: CmsTerm, slug_by_id: Dict[str, str]) -> Dict[str, Any]:
        item = {field: getattr(term, field) for field in _EXPORT_FIELDS}
        parent_id = str(term.parent_id) if term.parent_id else None
        item["parent_slug"] = slug_by_id.get(parent_id) if parent_id else None
        return item

    # ── import ───────────────────────────────────────────────────────────────

    def import_terms(self, payload: Dict[str, Any]) -> Dict[str, int]:
        """Upsert the envelope's terms by ``(term_type, slug)``.

        Returns ``{"created": n, "updated": m}``. Two passes: pass 1 upserts
        every row (parents resolvable in any order), pass 2 links ``parent_slug``.
        """
        items = self._validated_items(payload)

        created = 0
        updated = 0
        for item in items:
            term, was_created = self._upsert(item)
            if was_created:
                created += 1
            else:
                updated += 1

        self._link_parents(items)
        return {"created": created, "updated": updated}

    def _validated_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            raise TermImportError("Payload must be a JSON object")
        items = payload.get("items")
        if not isinstance(items, list):
            raise TermImportError("Payload 'items' must be a list")

        for item in items:
            term_type = (item.get("term_type") or "").strip()
            if not term_type_registry.is_registered(term_type):
                raise TermImportError(f"Unknown term type '{term_type}'")
            if not (item.get("name") or "").strip():
                raise TermImportError("Each item requires a 'name'")
        return items

    def _upsert(self, item: Dict[str, Any]) -> tuple[CmsTerm, bool]:
        term_type = item["term_type"].strip()
        name = item["name"].strip()
        slug = (item.get("slug") or slugify(name)).strip("/")

        existing = self._repo.find_by_type_and_slug(term_type, slug)
        term = existing or CmsTerm()
        term.term_type = term_type
        term.slug = slug
        term.name = name
        term.description = item.get("description")
        term.seo_excluded = item.get("seo_excluded", False)
        term.sort_order = item.get("sort_order", 0)
        # Parents are linked in pass 2 so item order is irrelevant.
        if existing is None:
            term.parent_id = None
        self._repo.save(term)
        return term, existing is None

    def _link_parents(self, items: List[Dict[str, Any]]) -> None:
        for item in items:
            parent_slug = item.get("parent_slug")
            if not parent_slug:
                continue
            term_type = item["term_type"].strip()
            slug = (item.get("slug") or slugify(item["name"])).strip("/")
            child = self._repo.find_by_type_and_slug(term_type, slug)
            parent = self._repo.find_by_type_and_slug(term_type, parent_slug)
            if parent is None:
                raise TermImportError(
                    f"parent_slug '{parent_slug}' not found for "
                    f"'{term_type}' term '{slug}'"
                )
            if child is not None and child.parent_id != parent.id:
                child.parent_id = parent.id
                self._repo.save(child)
