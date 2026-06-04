"""PostService — business logic for the unified post entity (S47.0).

Responsibilities:
  - type validation via the post-type registry (fail-fast on unknown);
  - slug uniqueness within a type;
  - hierarchy validation (parent only for hierarchical types, parent must
    itself be a hierarchical-type post, cycles refused);
  - status-transition validation across the D9 lifecycle;
  - the scheduled→published tick;
  - term assignment;
  - a ``content.changed`` event on every status change and content edit
    (consumed by the 47.1 prerender writer).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vbwd.events.dispatcher import Event

from plugins.cms.src.models.cms_post import (
    CmsPost,
    POST_STATUS_DRAFT,
    POST_STATUS_PENDING,
    POST_STATUS_SCHEDULED,
    POST_STATUS_PUBLISHED,
    POST_STATUS_PRIVATE,
    POST_STATUS_TRASH,
)
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services._slug import slugify


CONTENT_CHANGED_EVENT = "content.changed"

# Legal status transitions (D9). Every status may also move to ``trash``
# (soft-delete). ``published``/``private`` are interchangeable; ``scheduled``
# auto-advances to ``published`` via the tick.
_ALLOWED_TRANSITIONS: Dict[str, set] = {
    POST_STATUS_DRAFT: {
        POST_STATUS_PENDING,
        POST_STATUS_SCHEDULED,
        POST_STATUS_PUBLISHED,
    },
    POST_STATUS_PENDING: {
        POST_STATUS_DRAFT,
        POST_STATUS_SCHEDULED,
        POST_STATUS_PUBLISHED,
    },
    POST_STATUS_SCHEDULED: {
        POST_STATUS_DRAFT,
        POST_STATUS_PENDING,
        POST_STATUS_PUBLISHED,
    },
    POST_STATUS_PUBLISHED: {POST_STATUS_PRIVATE, POST_STATUS_DRAFT},
    POST_STATUS_PRIVATE: {POST_STATUS_PUBLISHED, POST_STATUS_DRAFT},
    POST_STATUS_TRASH: set(),
}

# Content fields whose edit fires content.changed (besides status).
_CONTENT_FIELDS = (
    "title",
    "excerpt",
    "featured_image_url",
    "content_json",
    "content_html",
    "type_data",
    "slug",
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


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce an ISO-8601 string (the editor's ``published_at``) to datetime.

    A datetime passes through; a falsy value clears the field; an unparseable
    string is treated as "no date" rather than raising, so a bad client value
    never blocks a save.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class PostNotFoundError(Exception):
    """Raised when a post id does not resolve."""


class PostSlugConflictError(Exception):
    """Raised when (type, slug) already exists."""


class UnknownPostTypeError(Exception):
    """Raised when creating a post with an unregistered type."""


class InvalidStatusTransitionError(Exception):
    """Raised when a status move is not permitted."""


class PostHierarchyError(Exception):
    """Raised for an illegal parent (wrong type, missing, or a cycle)."""


class InvalidLayoutOrStyleError(Exception):
    """Raised when a provided layout_id / style_id does not resolve."""


class PostService:
    """Service for managing unified posts."""

    def __init__(
        self,
        repo,
        term_repo,
        post_term_repo,
        event_dispatcher=None,
        layout_repo=None,
        style_repo=None,
    ) -> None:
        self._repo = repo
        self._term_repo = term_repo
        self._post_term_repo = post_term_repo
        self._event_dispatcher = event_dispatcher
        # Optional layout/style repos: when present, a provided layout_id /
        # style_id is validated to exist (mirrors how cms_page is themed). When
        # absent the ids are persisted unchecked, so a caller that does not wire
        # them keeps working (the disabled-validation path).
        self._layout_repo = layout_repo
        self._style_repo = style_repo

    # ── reads ────────────────────────────────────────────────────────────

    def _with_resolved_style(self, dto: Dict[str, Any]) -> Dict[str, Any]:
        """Augment a post dict with resolved_style_id / resolved_style_source.

        Mirrors CmsPageService._with_resolved_style so a post/page without an
        explicit style_id picks up the admin-designated default style:
          - Explicit style_id wins (source='explicit').
          - Otherwise an active default style is used (source='default').
          - Otherwise both fields are None.

        A missing/absent style_repo is tolerated — the fields still appear as
        None so the public renderer can rely on their presence.
        """
        style_id = dto.get("style_id")
        if style_id:
            dto["resolved_style_id"] = str(style_id)
            dto["resolved_style_source"] = "explicit"
            return dto
        default = None
        if self._style_repo is not None and hasattr(self._style_repo, "find_default"):
            default = self._style_repo.find_default()
        if default is not None and getattr(default, "is_active", True):
            dto["resolved_style_id"] = str(default.id)
            dto["resolved_style_source"] = "default"
        else:
            dto["resolved_style_id"] = None
            dto["resolved_style_source"] = None
        return dto

    def _with_term_ids(self, dto: Dict[str, Any], post_id: Any) -> Dict[str, Any]:
        """Attach the post's linked term ids so editors/lists can show the
        selected categories + tags (cms_post.to_dict has no term info)."""
        links = self._post_term_repo.find_by_post(str(post_id))
        dto["term_ids"] = [str(link.term_id) for link in links]
        return dto

    def get_post(self, post_id: str) -> Dict[str, Any]:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")
        return self._with_term_ids(self._with_resolved_style(post.to_dict()), post.id)

    def list_posts(
        self,
        post_type: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
    ) -> Dict[str, Any]:
        result = self._repo.find_paginated(
            post_type=post_type,
            status=status,
            search=(search or None) and search.strip() or None,
            page=page,
            per_page=per_page,
            newest_first=newest_first,
        )
        return self._serialize_page(result)

    def list_posts_by_term(
        self,
        term_type: str,
        term_slug: str,
        post_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
    ) -> Dict[str, Any]:
        result = self._repo.find_by_term_slug(
            term_type=term_type,
            term_slug=term_slug,
            post_type=post_type,
            status=status,
            page=page,
            per_page=per_page,
            newest_first=newest_first,
        )
        return self._serialize_page(result)

    def resolve_published_path(
        self, post_type: str, path: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve a (possibly nested) public path for a post type.

        A flat ``slug`` column stores the full path (e.g. ``about/team``),
        mirroring cms_page's full-path convention — a direct column match.
        """
        normalized = path.strip("/")
        post = self._repo.find_by_type_and_slug(post_type, normalized)
        if not post:
            return None
        return self._with_resolved_style(post.to_dict())

    # ── writes ───────────────────────────────────────────────────────────

    def create_post(self, data: Dict[str, Any]) -> Dict[str, Any]:
        post_type = (data.get("type") or "").strip()
        if not post_type_registry.is_registered(post_type):
            raise UnknownPostTypeError(f"Unknown post type '{post_type}'")

        title = (data.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        slug = (data.get("slug") or slugify(title)).strip("/")
        if self._repo.find_by_type_and_slug(post_type, slug):
            raise PostSlugConflictError(
                f"A '{post_type}' post with slug '{slug}' already exists"
            )

        parent_id = data.get("parent_id")
        if parent_id:
            self._validate_parent(post_type, parent_id, child_id=None)

        post = CmsPost()
        post.type = post_type
        post.slug = slug
        post.title = title
        post.excerpt = data.get("excerpt")
        post.featured_image_url = data.get("featured_image_url")
        post.content_json = data.get("content_json") or {}
        post.content_html = data.get("content_html")
        post.type_data = data.get("type_data")
        post.author_id = data.get("author_id")
        post.parent_id = parent_id
        post.status = data.get("status") or POST_STATUS_DRAFT
        post.language = data.get("language") or "en"
        post.translation_group_id = data.get("translation_group_id")
        post.sort_order = data.get("sort_order", 0)
        self._apply_seo(post, data)
        self._apply_layout_style(post, data)
        if post.status == POST_STATUS_PUBLISHED and not post.published_at:
            post.published_at = datetime.now(timezone.utc)

        self._repo.save(post)
        self._emit_content_changed(post, reason="created")
        return post.to_dict()

    def update_post(self, post_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")

        if "slug" in data:
            new_slug = (data["slug"] or "").strip("/")
            existing = self._repo.find_by_type_and_slug(post.type, new_slug)
            if existing and str(existing.id) != str(post.id):
                raise PostSlugConflictError(
                    f"A '{post.type}' post with slug '{new_slug}' already exists"
                )
            post.slug = new_slug

        if "parent_id" in data:
            parent_id = data["parent_id"]
            if parent_id:
                self._validate_parent(post.type, parent_id, child_id=str(post.id))
            post.parent_id = parent_id

        for field in (
            "title",
            "excerpt",
            "featured_image_url",
            "content_json",
            "content_html",
            "type_data",
            "author_id",
            "language",
            "translation_group_id",
            "sort_order",
        ):
            if field in data:
                setattr(post, field, data[field])
        # published_at (e.g. a scheduled date) is applied before the status
        # transition so publishing keeps an explicit date over "now".
        if "published_at" in data:
            post.published_at = _parse_datetime(data["published_at"])
        self._apply_seo(post, data)
        self._apply_layout_style(post, data)

        # Status is part of the editor's Save payload; route it through the same
        # validated transition as change_status so the state machine holds.
        status_changed = False
        if "status" in data and data["status"]:
            status_changed = self._transition_status(post, data["status"])

        self._repo.save(post)
        if status_changed or any(field in data for field in _CONTENT_FIELDS):
            self._emit_content_changed(post, reason="updated")
        return post.to_dict()

    def _transition_status(self, post: CmsPost, target_status: str) -> bool:
        """Validate + apply a status transition in place. No-op if unchanged.

        Returns True when the status actually changed. Raises
        InvalidStatusTransitionError for a disallowed move.
        """
        if target_status == post.status:
            return False

        if target_status == POST_STATUS_TRASH:
            allowed = True
        else:
            allowed = target_status in _ALLOWED_TRANSITIONS.get(post.status, set())
        if not allowed:
            raise InvalidStatusTransitionError(
                f"Cannot move post from '{post.status}' to '{target_status}'"
            )

        post.status = target_status
        if target_status == POST_STATUS_PUBLISHED and not post.published_at:
            post.published_at = datetime.now(timezone.utc)
        return True

    def change_status(self, post_id: str, target_status: str) -> Dict[str, Any]:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")

        if not self._transition_status(post, target_status):
            return post.to_dict()

        self._repo.save(post)
        self._emit_content_changed(post, reason="status_changed")
        return post.to_dict()

    def delete_post(self, post_id: str) -> None:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")
        self._repo.delete(post_id)

    def assign_terms(self, post_id: str, term_ids: List[str]) -> None:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")
        self._post_term_repo.replace_for_post(post_id, term_ids)

    def regenerate_prerender(self) -> int:
        """Re-emit ``content.changed`` for every published post so the SEO
        prerender writer (re)writes ``${VAR_DIR}/seo/<slug>.html`` for content
        that predates the writer or was created by a bulk backfill/import.

        Returns the number of posts re-emitted.
        """
        posts = self._repo.find_all_published()
        for post in posts:
            self._emit_content_changed(post, reason="regenerated")
        return len(posts)

    def publish_due_scheduled(self) -> List[str]:
        """Publish scheduled posts whose ``published_at`` has passed.

        Called by the TESTING-guarded scheduler tick. Returns the ids of the
        posts that were published. Fires ``content.changed`` for each.
        """
        published_ids: List[str] = []
        for post in self._repo.find_scheduled_due():
            post.status = POST_STATUS_PUBLISHED
            self._repo.save(post)
            self._emit_content_changed(post, reason="scheduled_published")
            published_ids.append(str(post.id))
        return published_ids

    # ── helpers ──────────────────────────────────────────────────────────

    def _validate_parent(
        self, post_type: str, parent_id: str, child_id: Optional[str]
    ) -> None:
        registered = post_type_registry.get_post_type(post_type)
        if not registered or not registered.hierarchical:
            raise PostHierarchyError(
                f"Post type '{post_type}' does not support a parent"
            )

        parent = self._repo.find_by_id(parent_id)
        if not parent:
            raise PostHierarchyError(f"Parent post '{parent_id}' not found")

        parent_type = post_type_registry.get_post_type(parent.type)
        if not parent_type or not parent_type.hierarchical:
            raise PostHierarchyError("Parent must itself be a hierarchical-type post")

        if child_id and self._creates_cycle(child_id, parent):
            raise PostHierarchyError("Parent assignment would create a cycle")

    def _creates_cycle(self, child_id: str, parent: CmsPost) -> bool:
        """True if making ``parent`` the parent of ``child_id`` forms a cycle."""
        ancestor: Optional[CmsPost] = parent
        seen = set()
        while ancestor is not None:
            if str(ancestor.id) == str(child_id):
                return True
            if str(ancestor.id) in seen:
                break
            seen.add(str(ancestor.id))
            if not ancestor.parent_id:
                break
            ancestor = self._repo.find_by_id(str(ancestor.parent_id))
        return False

    def _apply_seo(self, post: CmsPost, data: Dict[str, Any]) -> None:
        for field in (
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
        ):
            if field in data:
                setattr(post, field, data[field])

    def _apply_layout_style(self, post: CmsPost, data: Dict[str, Any]) -> None:
        """Apply + validate the layout/style fields.

        A non-empty ``layout_id`` / ``style_id`` must resolve through the wired
        repo (mirrors how a page is themed); a missing one raises so the route
        can answer 400. ``None`` clears the link.
        """
        if "layout_id" in data:
            post.layout_id = self._resolve_themed_id(
                self._layout_repo, data["layout_id"], "layout"
            )
        if "style_id" in data:
            post.style_id = self._resolve_themed_id(
                self._style_repo, data["style_id"], "style"
            )

    def _resolve_themed_id(self, repo, value, label: str):
        if not value:
            return None
        if repo is not None and repo.find_by_id(str(value)) is None:
            raise InvalidLayoutOrStyleError(f"Unknown {label}_id '{value}'")
        return value

    def _serialize_page(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "items": [
                self._with_term_ids(item.to_dict(), item.id)
                for item in result.get("items", [])
            ],
            "total": result.get("total", 0),
            "page": result.get("page", 1),
            "per_page": result.get("per_page", 20),
            "pages": result.get("pages", 1),
        }

    def _emit_content_changed(self, post: CmsPost, reason: str) -> None:
        if self._event_dispatcher is None:
            return
        self._event_dispatcher.dispatch(
            Event(
                name=CONTENT_CHANGED_EVENT,
                data={
                    "post_id": str(post.id),
                    "type": post.type,
                    "slug": post.slug,
                    "status": post.status,
                    "reason": reason,
                },
            )
        )
