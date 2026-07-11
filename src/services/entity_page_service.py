"""EntityPageService — the generic entity-page capability (S128).

One reusable "content page + SEO" attachable to any owning entity, built ON the
existing CMS content stack (``CmsPost`` + content blocks + widgets + SEO) — no
new content model. The sellable entity stays distinct from its page: the link
lives in ``cms_entity_page`` (SRP), never smeared onto the entity or the post.

Responsibilities:
  - ``get_or_scaffold`` — project the linked post, or an empty content+SEO
    scaffold when the owner has no page yet (Liskov: unlinked never crashes);
  - ``save`` — resolve-or-create the ``entity_page`` post through the CMS post
    service (content + blocks + all SEO), then upsert the link (idempotent);
  - ``delete_for_owner`` — drop the owner's link(s) + linked post(s);
  - ``public_view`` — a published read projection; the ORM object never leaves
    the service.

Collaborators are injected (DI): the CMS post service (write path), the link
repository, the post repository (read), and the content-block repository (block
projection). The service depends on those abstractions, not on globals.
"""
from typing import Any, Dict, Optional

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.services.post_service import PostNotFoundError


# An entity page is a CmsPost of this (non-routable) type.
ENTITY_PAGE_POST_TYPE = "entity_page"

# The slug basis for an entity page's backing post. Deterministic + unique per
# (owner_type, owner_id, slot) within the ``entity_page`` type's slug scope, so
# a re-save resolves the same post. Never a public URL (routable=False).
ENTITY_PAGE_SLUG_PREFIX = "entity-page"

# The 10 SEO fields an entity page carries — the exact CmsPost SEO column set.
SEO_FIELD_NAMES = (
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

# Empty/default value per SEO field for the "no page yet" scaffold. Mirrors the
# CmsPost column defaults (robots indexes by default; seo_excluded off).
SEO_SCAFFOLD_DEFAULTS: Dict[str, Any] = {
    "meta_title": "",
    "meta_description": "",
    "meta_keywords": "",
    "og_title": "",
    "og_description": "",
    "og_image_url": "",
    "canonical_url": "",
    "robots": "index,follow",
    "schema_json": None,
    "seo_excluded": False,
}

# String SEO fields projected as "" (not None) so the payload shape is stable.
_STRING_SEO_FIELDS = frozenset(
    name for name, default in SEO_SCAFFOLD_DEFAULTS.items() if default == ""
)


class EntityPageService:
    """Author/read a content+SEO page attached to any owning entity."""

    def __init__(
        self,
        post_service,
        entity_page_repo,
        post_repo,
        content_block_repo,
    ) -> None:
        self._post_service = post_service
        self._entity_page_repo = entity_page_repo
        self._post_repo = post_repo
        self._content_block_repo = content_block_repo

    # ── reads ────────────────────────────────────────────────────────────

    def get_or_scaffold(
        self, owner_type: str, owner_id: str, slot: str = "main"
    ) -> Dict[str, Any]:
        """Project the linked post, or an empty scaffold when unlinked."""
        link = self._entity_page_repo.get_by_owner(owner_type, owner_id, slot)
        if link is None:
            return self._empty_scaffold()
        post = self._post_repo.find_by_id(str(link.post_id))
        if post is None:
            return self._empty_scaffold()
        return self._project_post(post)

    def public_view(
        self, owner_type: str, owner_id: str, slot: str = "main"
    ) -> Optional[Dict[str, Any]]:
        """Published projection for the public page, or None when unlinked /
        unpublished. The CmsPost never leaves the service."""
        link = self._entity_page_repo.get_by_owner(owner_type, owner_id, slot)
        if link is None:
            return None
        post = self._post_repo.find_by_id(str(link.post_id))
        if post is None or post.status != POST_STATUS_PUBLISHED:
            return None
        return self._project_post(post)

    # ── writes ───────────────────────────────────────────────────────────

    def save(
        self,
        owner_type: str,
        owner_id: str,
        slot: str,
        fields: Dict[str, Any],
        actor: Any = None,
    ) -> Dict[str, Any]:
        """Resolve-or-create the entity_page post, then upsert the link.

        Idempotent: a first save creates the post + link; a later save updates
        the same post in place. Returns the saved projection.
        """
        payload = self._build_post_payload(fields)
        link = self._entity_page_repo.get_by_owner(owner_type, owner_id, slot)
        if link is None:
            create_data = {
                **payload,
                "type": ENTITY_PAGE_POST_TYPE,
                "title": self._derive_title(owner_type, owner_id, slot, fields),
                "slug": self._derive_slug(owner_type, owner_id, slot),
                "status": POST_STATUS_PUBLISHED,
            }
            author_id = self._actor_id(actor)
            if author_id is not None:
                create_data["author_id"] = author_id
            created = self._post_service.create_post(create_data)
            self._entity_page_repo.upsert(owner_type, owner_id, slot, created["id"])
        else:
            self._post_service.update_post(str(link.post_id), payload)
        return self.get_or_scaffold(owner_type, owner_id, slot)

    def delete_for_owner(self, owner_type: str, owner_id: str) -> None:
        """Delete an owner's entity page(s): the linked post(s) + link(s).

        Deleting the post cascades the link (FK ondelete CASCADE); the explicit
        ``delete_by_owner`` afterwards is a defensive no-op that also removes any
        orphaned link whose post was already gone.
        """
        for link in self._entity_page_repo.find_by_owner(owner_type, owner_id):
            try:
                self._post_service.delete_post(str(link.post_id))
            except PostNotFoundError:
                continue
        self._entity_page_repo.delete_by_owner(owner_type, owner_id)

    # ── helpers ──────────────────────────────────────────────────────────

    def _build_post_payload(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten the FE fields into a CmsPost create/update payload.

        Content fields map straight through; ``content_blocks`` (when present)
        is forwarded to the post service's block upsert; the nested ``seo`` block
        is flattened onto the top-level SEO keys the post service expects.
        """
        payload: Dict[str, Any] = {
            "content_html": fields.get("content_html", ""),
            "content_json": fields.get("content_json") or {},
            "source_css": fields.get("source_css", ""),
        }
        if "content_blocks" in fields:
            payload["content_blocks"] = fields.get("content_blocks") or []
        seo = fields.get("seo") or {}
        for name in SEO_FIELD_NAMES:
            if name in seo:
                payload[name] = seo[name]
        return payload

    def _empty_scaffold(self) -> Dict[str, Any]:
        return {
            "post_id": None,
            "content_html": "",
            "content_json": {},
            "source_css": "",
            "content_blocks": [],
            "seo": dict(SEO_SCAFFOLD_DEFAULTS),
        }

    def _project_post(self, post: Any) -> Dict[str, Any]:
        blocks = self._content_block_repo.find_by_post(str(post.id))
        return {
            "post_id": str(post.id),
            "content_html": post.content_html or "",
            "content_json": post.content_json or {},
            "source_css": post.source_css or "",
            "content_blocks": [block.to_dict() for block in blocks],
            "seo": self._seo_from_post(post),
        }

    @staticmethod
    def _seo_from_post(post: Any) -> Dict[str, Any]:
        seo: Dict[str, Any] = {}
        for name in SEO_FIELD_NAMES:
            value = getattr(post, name, None)
            if value is None and name in _STRING_SEO_FIELDS:
                value = ""
            seo[name] = value
        return seo

    @staticmethod
    def _derive_title(
        owner_type: str, owner_id: str, slot: str, fields: Dict[str, Any]
    ) -> str:
        """A non-empty title for the backing post (CmsPost.title is NOT NULL).

        An explicit ``title`` in the fields wins; otherwise a stable derived
        label. The title is internal — an entity page is never listed as a page.
        """
        explicit = (fields.get("title") or "").strip()
        if explicit:
            return explicit
        return f"Entity page {owner_type}/{owner_id}/{slot}"

    @staticmethod
    def _derive_slug(owner_type: str, owner_id: str, slot: str) -> str:
        return f"{ENTITY_PAGE_SLUG_PREFIX}/{owner_type}/{owner_id}/{slot}"

    @staticmethod
    def _actor_id(actor: Any) -> Optional[str]:
        actor_id = getattr(actor, "id", None)
        return str(actor_id) if actor_id is not None else None
