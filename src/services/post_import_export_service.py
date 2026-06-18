"""PostImportExportService — VBWD-standard posts export/import.

Round-trips the unified ``cms_post`` set as a portable JSON envelope so the
fe-admin posts list can back up / restore / move posts between environments.
Mirrors the R1 ``TermImportExportService`` pattern: the envelope carries the
**natural key** ``(type, slug)`` and slug-based references (``layout_slug`` /
``style_slug`` / ``parent_slug`` and a ``terms`` list of ``term_type`` + ``slug``)
instead of internal UUIDs, so an import re-resolves identity on the target DB.

Upsert is by ``(type, slug)``. Parents and terms are resolved in a second pass
(every row created/updated first) so item order in the payload does not matter.
Idempotent: a re-import of the same payload creates nothing new.

Single responsibility: only export/import. Post CRUD stays in ``PostService``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services._slug import slugify

ENVELOPE_VERSION = 1
ENVELOPE_ENTITY = "cms_post"

# Portable, id-free scalar fields copied verbatim on export/import.
_SCALAR_FIELDS = (
    "type",
    "slug",
    "title",
    "excerpt",
    "featured_image_url",
    "content_html",
    "content_json",
    "source_css",
    "status",
    "language",
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
    "seo_excluded",
)


class PostImportError(Exception):
    """Raised when an import payload is malformed or references unknown data."""


class PostImportExportService:
    """Export / import posts as a VBWD-standard JSON envelope."""

    def __init__(
        self,
        post_repo,
        layout_repo,
        style_repo,
        term_repo,
        post_term_repo,
        content_block_repo=None,
        post_widget_repo=None,
        widget_repo=None,
    ) -> None:
        self._post_repo = post_repo
        self._layout_repo = layout_repo
        self._style_repo = style_repo
        self._term_repo = term_repo
        self._post_term_repo = post_term_repo
        # S55 optional repos. When wired, the envelope additionally carries the
        # post's extra content areas (``content_blocks``) and post-level widget
        # assignments (``page_assignments``); when absent the lean envelope is
        # produced unchanged (back-compat with existing callers/exports).
        self._content_block_repo = content_block_repo
        self._post_widget_repo = post_widget_repo
        self._widget_repo = widget_repo

    # ── export ───────────────────────────────────────────────────────────────

    def export_posts(
        self,
        post_type: Optional[str] = None,
        ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return the VBWD-standard envelope for all posts (or one type).

        When ``ids`` is given, only those posts are exported ("export selected").
        """
        posts = self._post_repo.find_paginated(
            post_type=post_type, per_page=100000
        ).get("items", [])
        if ids is not None:
            wanted = {str(i) for i in ids}
            posts = [
                post
                for post in posts
                if str(post.id) in wanted or (post.slug and post.slug in wanted)
            ]
        slug_by_post_id = {str(post.id): post.slug for post in posts}
        return {
            "version": ENVELOPE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entity": ENVELOPE_ENTITY,
            "items": [self._to_item(post, slug_by_post_id) for post in posts],
        }

    def _to_item(
        self, post: CmsPost, slug_by_post_id: Dict[str, str]
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {field: getattr(post, field) for field in _SCALAR_FIELDS}
        item["layout_slug"] = self._slug_of(self._layout_repo, post.layout_id)
        item["style_slug"] = self._slug_of(self._style_repo, post.style_id)
        parent_id = str(post.parent_id) if post.parent_id else None
        item["parent_slug"] = slug_by_post_id.get(parent_id) if parent_id else None
        item["terms"] = self._terms_of(post)
        if self._content_block_repo is not None:
            item["content_blocks"] = self._content_blocks_of(post)
        if self._post_widget_repo is not None:
            item["page_assignments"] = self._page_assignments_of(post)
        return item

    def _content_blocks_of(self, post: CmsPost) -> List[Dict[str, Any]]:
        """The post's additional content areas, id-free (S55)."""
        blocks: List[Dict[str, Any]] = []
        for block in self._content_block_repo.find_by_post(str(post.id)):
            blocks.append(
                {
                    "area_name": block.area_name,
                    "content_html": block.content_html,
                    "content_json": block.content_json,
                    "source_css": block.source_css,
                    "sort_order": block.sort_order,
                }
            )
        return blocks

    def _page_assignments_of(self, post: CmsPost) -> List[Dict[str, Any]]:
        """The post's widget assignments, with widget refs by slug (S55)."""
        assignments: List[Dict[str, Any]] = []
        for assignment in self._post_widget_repo.find_by_post(str(post.id)):
            widget = (
                self._widget_repo.find_by_id(str(assignment.widget_id))
                if self._widget_repo is not None
                else None
            )
            assignments.append(
                {
                    "widget_slug": widget.slug if widget else None,
                    "area_name": assignment.area_name,
                    "sort_order": assignment.sort_order,
                    "required_access_level_ids": (
                        assignment.required_access_level_ids or []
                    ),
                    "config_override": assignment.config_override,
                }
            )
        return assignments

    def _slug_of(self, repo, obj_id) -> Optional[str]:
        if not obj_id:
            return None
        obj = repo.find_by_id(str(obj_id))
        return obj.slug if obj else None

    def _terms_of(self, post: CmsPost) -> List[Dict[str, str]]:
        terms: List[Dict[str, str]] = []
        for link in self._post_term_repo.find_by_post(str(post.id)):
            term = self._term_repo.find_by_id(str(link.term_id))
            if term is not None:
                terms.append({"term_type": term.term_type, "slug": term.slug})
        return terms

    # ── import ───────────────────────────────────────────────────────────────

    def import_posts(self, payload: Dict[str, Any]) -> Dict[str, int]:
        """Upsert the envelope's posts by ``(type, slug)``.

        Returns ``{"created": n, "updated": m}``. Two passes: pass 1 upserts
        every row (parents resolvable in any order), pass 2 links parents +
        terms.
        """
        items = self._validated_items(payload)

        created = 0
        updated = 0
        for item in items:
            _post, was_created = self._upsert(item)
            if was_created:
                created += 1
            else:
                updated += 1

        self._link_parents_and_terms(items)
        return {"created": created, "updated": updated}

    def _validated_items(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Accept the canonical envelope ({"items": [...]}), a bare list of
        # items, or a single item object — so a one-page export (legacy
        # cms_page shape) imports as readily as a full bundle.
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
            items = payload["items"]
        elif isinstance(payload, dict) and (payload.get("slug") or payload.get("name")):
            items = [payload]
        else:
            raise PostImportError("Payload 'items' must be a list")

        for item in items:
            post_type = (item.get("type") or "").strip()
            if not post_type_registry.is_registered(post_type):
                raise PostImportError(f"Unknown post type '{post_type}'")
            # Legacy cms_page exports carry ``name`` instead of ``title``.
            if not (item.get("title") or item.get("name") or "").strip():
                raise PostImportError("Each item requires a 'title'")
        return items

    def _upsert(self, item: Dict[str, Any]) -> tuple[CmsPost, bool]:
        post_type = item["type"].strip()
        title = (item.get("title") or item.get("name") or "").strip()
        slug = (item.get("slug") or slugify(title)).strip("/")

        existing = self._post_repo.find_by_type_and_slug(post_type, slug)
        post = existing or CmsPost()
        post.type = post_type
        post.slug = slug
        post.title = title
        post.excerpt = item.get("excerpt")
        post.featured_image_url = item.get("featured_image_url")
        post.content_json = item.get("content_json") or {}
        post.content_html = item.get("content_html")
        # Page/post own CSS (editor "CSS" tab) travels with the export.
        post.source_css = item.get("source_css")
        post.status = self._resolve_status(item, existing)
        post.language = item.get("language") or "en"
        post.sort_order = item.get("sort_order", 0)
        post.layout_id = self._resolve_ref(self._layout_repo, item.get("layout_slug"))
        post.style_id = self._resolve_ref(self._style_repo, item.get("style_slug"))
        self._apply_seo(post, item)
        # Parents are linked in pass 2 so item order is irrelevant.
        if existing is None:
            post.parent_id = None
            # New posts need a preview token so the admin can build a working
            # ?preview_token= URL (mirrors PostService.create_post). An
            # existing row keeps its token.
            if not post.preview_token:
                post.preview_token = uuid4().hex
        self._post_repo.save(post)
        return post, existing is None

    def _resolve_status(self, item: Dict[str, Any], existing: Optional[CmsPost]) -> str:
        """Status precedence on import: explicit ``status`` → legacy
        ``is_published`` → the existing row's status (never silently demote a
        published page to draft on re-import) → ``draft`` for a brand-new row.
        """
        explicit = (item.get("status") or "").strip()
        if explicit:
            return explicit
        if "is_published" in item:
            return "published" if item.get("is_published") else "draft"
        if existing is not None:
            return existing.status
        return "draft"

    def _apply_seo(self, post: CmsPost, item: Dict[str, Any]) -> None:
        post.meta_title = item.get("meta_title")
        post.meta_description = item.get("meta_description")
        post.meta_keywords = item.get("meta_keywords")
        post.og_title = item.get("og_title")
        post.og_description = item.get("og_description")
        post.og_image_url = item.get("og_image_url")
        post.canonical_url = item.get("canonical_url")
        post.robots = item.get("robots") or "index,follow"
        post.schema_json = item.get("schema_json")
        post.seo_excluded = item.get("seo_excluded", False)

    def _resolve_ref(self, repo, slug: Optional[str]):
        """Resolve a layout/style slug to its id; unknown slug → None."""
        if not slug:
            return None
        obj = repo.find_by_slug(slug)
        return obj.id if obj else None

    def _link_parents_and_terms(self, items: List[Dict[str, Any]]) -> None:
        for item in items:
            post_type = item["type"].strip()
            slug = (item.get("slug") or slugify(item["title"])).strip("/")
            post = self._post_repo.find_by_type_and_slug(post_type, slug)
            if post is None:
                continue
            self._link_parent(post, item)
            self._link_terms(post, item)
            self._link_content_blocks(post, item)
            self._link_page_assignments(post, item)

    def _link_content_blocks(self, post: CmsPost, item: Dict[str, Any]) -> None:
        if self._content_block_repo is None:
            return
        blocks = item.get("content_blocks")
        if not isinstance(blocks, list) or not blocks:
            return
        normalized = [block for block in blocks if block.get("area_name")]
        if normalized:
            self._content_block_repo.replace_for_post(str(post.id), normalized)

    def _link_page_assignments(self, post: CmsPost, item: Dict[str, Any]) -> None:
        if self._post_widget_repo is None:
            return
        page_assignments = item.get("page_assignments")
        if not isinstance(page_assignments, list) or not page_assignments:
            return
        resolved: List[Dict[str, Any]] = []
        for assignment in page_assignments:
            widget = (
                self._widget_repo.find_by_slug(assignment.get("widget_slug"))
                if self._widget_repo is not None and assignment.get("widget_slug")
                else None
            )
            if widget is None:
                continue
            resolved.append(
                {
                    "widget_id": str(widget.id),
                    "area_name": assignment.get("area_name"),
                    "sort_order": assignment.get("sort_order", 0),
                    "required_access_level_ids": assignment.get(
                        "required_access_level_ids", []
                    ),
                    "config_override": assignment.get("config_override"),
                }
            )
        if resolved:
            self._post_widget_repo.replace_for_post(str(post.id), resolved)

    def _link_parent(self, post: CmsPost, item: Dict[str, Any]) -> None:
        parent_slug = item.get("parent_slug")
        if not parent_slug:
            return
        parent = self._post_repo.find_by_type_and_slug(post.type, parent_slug)
        if parent is not None and post.parent_id != parent.id:
            post.parent_id = parent.id
            self._post_repo.save(post)

    def _link_terms(self, post: CmsPost, item: Dict[str, Any]) -> None:
        term_refs = item.get("terms")
        if not term_refs:
            return
        term_ids: List[str] = []
        for ref in term_refs:
            term = self._term_repo.find_by_type_and_slug(
                (ref.get("term_type") or "").strip(), (ref.get("slug") or "").strip()
            )
            if term is not None:
                term_ids.append(str(term.id))
        if term_ids:
            self._post_term_repo.replace_for_post(str(post.id), term_ids)
