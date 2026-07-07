"""ContentIngestService — the cms API content-ingestion composer (S52.8).

Composes the existing cms services to turn an ingestion payload (from a holder
of the ``cms:posts:create`` API-key scope) into a post/page authored as the
key's user. Owns **no** persistence (SRP/DRY) — every write goes through
``PostService`` / ``TermService`` / ``CmsImageService``.
"""
import base64
import binascii
from typing import Any, Dict, List, Optional
from uuid import UUID

from plugins.cms.src.services._slug import slugify

DEFAULT_TYPE = "post"
DEFAULT_STATUS = "draft"

# Posts ingested through this path are tagged on the core ``cms_post`` entity
# type (categories stay on the cms_term taxonomy — D7).
TAG_ENTITY_TYPE = "cms_post"

# SEO fields lifted verbatim from the ``seo`` sub-object onto the post payload
# (PostService._apply_seo consumes these top-level keys).
_SEO_FIELDS = (
    "meta_title",
    "meta_description",
    "meta_keywords",
    "og_title",
    "og_description",
    "og_image_url",
    "canonical_url",
    "robots",
    "schema_json",
)


class ContentIngestService:
    """Create a cms post/page from an API ingestion payload."""

    def __init__(self, *, post_service, term_service, image_service, tags_port) -> None:
        self._post_service = post_service
        self._term_service = term_service
        self._image_service = image_service
        # The core tags port (``ITagsAndCustomFields``) — categories stay on the
        # cms_term taxonomy, tags go to the single core catalog (D7).
        self._tags_port = tags_port

    def ingest(self, payload: Dict[str, Any], *, user_id: Any) -> Dict[str, Any]:
        """Validate + create a post/page owned by ``user_id``.

        Raises ``ValueError`` for a bad payload (missing title, undecodable
        image) so the route can answer 400. Unknown post types surface as the
        ``PostService`` error the route already maps.
        """
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        data: Dict[str, Any] = {
            "type": payload.get("type") or DEFAULT_TYPE,
            "title": title,
            "author_id": user_id,
            "status": payload.get("status") or DEFAULT_STATUS,
        }
        for field in ("slug", "excerpt", "content_html", "source_css"):
            if payload.get(field) is not None:
                data[field] = payload[field]

        self._apply_seo(data, payload.get("seo"))

        featured_image_url = self._maybe_upload_image(payload.get("image"))
        if featured_image_url:
            data["featured_image_url"] = featured_image_url

        created = self._post_service.create_post(data)

        category_term_ids = self._resolve_category_terms(payload)
        if category_term_ids:
            self._post_service.assign_terms(created["id"], category_term_ids)

        self._apply_tags(created["id"], payload)

        return {
            "id": created.get("id"),
            "slug": created.get("slug"),
            "type": created.get("type"),
            "status": created.get("status"),
            "featured_image_url": created.get("featured_image_url")
            or featured_image_url,
        }

    def _apply_seo(self, data: Dict[str, Any], seo: Optional[Dict[str, Any]]) -> None:
        if not seo:
            return
        for field in _SEO_FIELDS:
            if seo.get(field) is not None:
                data[field] = seo[field]

    def _resolve_category_terms(self, payload: Dict[str, Any]) -> List[Any]:
        """Resolve category entries to cms_term ids (tags go via the core port).

        Each entry is EITHER a plain ``str`` (a top-level category, the original
        behaviour) OR a ``{"name": str, "parent": str | None}`` dict. A dict with
        a non-null ``parent`` lands the post in BOTH the parent category and the
        child subcategory: the parent is find-or-created top-level, then the child
        under it. All resolved ids (parents included) are collected and deduped so
        assign_terms receives each term once.
        """
        term_ids: List[Any] = []
        seen_ids: set = set()
        for entry in payload.get("categories") or []:
            for term_id in self._resolve_category_entry(entry):
                if term_id not in seen_ids:
                    seen_ids.add(term_id)
                    term_ids.append(term_id)
        return term_ids

    def _resolve_category_entry(self, entry: Any) -> List[Any]:
        """Resolve one category entry to the term ids it contributes."""
        if isinstance(entry, dict):
            name = (entry.get("name") or "").strip()
            if not name:
                return []
            parent_name = (entry.get("parent") or "").strip()
            if parent_name:
                parent_term = self._term_service.find_or_create("category", parent_name)
                child_term = self._term_service.find_or_create(
                    "category", name, parent_id=parent_term["id"]
                )
                return [parent_term["id"], child_term["id"]]
            return [self._term_service.find_or_create("category", name)["id"]]
        return [self._term_service.find_or_create("category", entry)["id"]]

    def _apply_tags(self, post_id: Any, payload: Dict[str, Any]) -> None:
        """Write the payload's ``tags`` to the core tag catalog (D7).

        Names are slugified (matching the cms_term slug rule the migrated tags
        carried), so re-ingesting the same tag name maps to one catalog row.
        """
        names = payload.get("tags") or []
        if not names:
            return
        slugs = [slug for slug in (slugify(name) for name in names) if slug]
        self._tags_port.set_tags(TAG_ENTITY_TYPE, UUID(str(post_id)), slugs)

    def _maybe_upload_image(self, image: Optional[Dict[str, Any]]) -> Optional[str]:
        if not image or not image.get("base64"):
            return None
        raw = self._decode_base64(image["base64"])
        uploaded = self._image_service.upload_image(
            file_data=raw,
            filename=image.get("filename") or "upload.bin",
            mime_type=image.get("mime_type") or "application/octet-stream",
        )
        return uploaded.get("url_path")

    @staticmethod
    def _decode_base64(value: str) -> bytes:
        # Tolerate a data-URL prefix ("data:<mime>;base64,<data>").
        if value.startswith("data:") and "," in value:
            value = value.split(",", 1)[1]
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("image.base64 is not valid base64")
