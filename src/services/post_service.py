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
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

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
from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, TAG_TERM_TYPE
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services._slug import slugify, unique_slug
from plugins.cms.src.services.term_permalink import (
    term_archive_path,
    humanize_term_slug,
)
from plugins.cms.src.services.permalink import (
    PermalinkRenderer,
    PrimaryCategory,
    PERMALINK_MODE_OFF,
)
from plugins.cms.src.services.seo_canonical import derive_canonical_url


CONTENT_CHANGED_EVENT = "content.changed"

# Core entity types a unified post is addressed as in the core tags/custom-fields
# index (``vbwd_entity_tag``). A ``page`` is a ``cms_page``; everything else a
# ``cms_post`` — mirrors the tags/custom-fields matrix scoping.
CORE_ENTITY_TYPE_POST = "cms_post"
CORE_ENTITY_TYPE_PAGE = "cms_page"


def core_entity_type_for_post_type(post_type: Optional[str]) -> str:
    """Map a unified post's ``type`` discriminator onto its core entity type.

    Single source of truth for the ``page → cms_page`` / else → ``cms_post``
    convention, reused by both the list-tag enrichment here and the detail
    route's per-post tag append (DRY — one mapping, no re-hardcoded strings).
    """
    return CORE_ENTITY_TYPE_PAGE if post_type == "page" else CORE_ENTITY_TYPE_POST


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
    # Trash is restorable to any working status (undo a delete).
    POST_STATUS_TRASH: {
        POST_STATUS_DRAFT,
        POST_STATUS_PENDING,
        POST_STATUS_SCHEDULED,
        POST_STATUS_PUBLISHED,
        POST_STATUS_PRIVATE,
    },
}

# Content fields whose edit fires content.changed (besides status).
_CONTENT_FIELDS = (
    "title",
    "excerpt",
    "featured_image_url",
    "content_json",
    "content_html",
    "source_css",
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
        content_block_repo=None,
        layout_widget_repo=None,
        routing_rule_repo=None,
        permalink_config=None,
        renderer=None,
        tags_port=None,
        post_widget_repo=None,
    ) -> None:
        self._repo = repo
        self._term_repo = term_repo
        self._post_term_repo = post_term_repo
        self._event_dispatcher = event_dispatcher
        # Optional per-area content-block repo (S55). When present, an optional
        # ``content_blocks`` key in the create/update payload upserts additional
        # content areas (the primary area stays on ``content_html``). Absent →
        # the feature is silently inert, so a caller that does not wire it keeps
        # working (the disabled-feature path).
        self._content_block_repo = content_block_repo
        # Optional per-post widget-placement repo (S55). When present, ``copy_post``
        # duplicates a post's ``cms_post_widget`` rows onto the copy (re-pointing
        # ``post_id``, keeping the shared ``widget_id``). Absent → the copy simply
        # carries no per-post widget overrides (the disabled-feature path).
        self._post_widget_repo = post_widget_repo
        # Optional layout/style repos: when present, a provided layout_id /
        # style_id is validated to exist (mirrors how cms_page is themed). When
        # absent the ids are persisted unchecked, so a caller that does not wire
        # them keeps working (the disabled-validation path). The repos also back
        # the admin-designated default (find_default) applied on PUBLIC reads.
        self._layout_repo = layout_repo
        self._style_repo = style_repo
        # Optional layout-widget (placement) repo. When present, an explicit
        # layout with ZERO widget placements ("not seeded") is treated as
        # unusable on PUBLIC reads and falls back to the default layout, so the
        # page renders chrome + body instead of blank. Absent → an explicit
        # layout is always honoured (the disabled-feature path).
        self._layout_widget_repo = layout_widget_repo
        # Permalink engine (S122). Optional — absent/``off`` config keeps today's
        # behaviour exactly (``slug`` used verbatim). ``routing_rule_repo`` backs
        # the auto-301 on a published-post rename; ``None`` disables the emission
        # (the disabled-feature path). ``permalink_config`` is the live cms config
        # blob (permalink keys + public_base_url + home_slug).
        self._routing_rule_repo = routing_rule_repo
        self._permalink_config = permalink_config or {}
        self._renderer = renderer or PermalinkRenderer()
        # Core tags port (S77). When present, LIST serialization batch-fetches
        # each post's tags (one bulk query per core entity type — no N+1) so the
        # fe archive card can render tag chips. Absent → items carry an empty
        # ``tags`` list, so a caller that does not wire it keeps working (the
        # disabled-feature path).
        self._tags_port = tags_port

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

    def _with_resolved_layout(self, dto: Dict[str, Any]) -> Dict[str, Any]:
        """Augment a post dict with resolved_layout_id / resolved_layout_source.

        Mirrors _with_resolved_style — the default is the cms_layout row
        flagged ``is_default`` (via layout_repo.find_default), not a config:
          - An explicit layout_id wins (source='explicit') *only when it is
            seeded* — i.e. it has ≥1 widget placement. An explicit layout with
            ZERO placements is unusable (it would render blank) and falls
            through to the default below.
          - Otherwise an active default layout is used (source='default').
          - Otherwise both fields resolve to None / 'none'.

        Applied on the PUBLIC payload only — the editor keeps the raw,
        possibly-empty layout_id so "no layout" stays truthful. A missing/
        absent layout_repo is tolerated — the fields still appear so the
        public renderer can rely on their presence.
        """
        layout_id = dto.get("layout_id")
        if layout_id and self._layout_is_seeded(layout_id):
            dto["resolved_layout_id"] = str(layout_id)
            dto["resolved_layout_source"] = "explicit"
            return dto
        default = None
        if self._layout_repo is not None and hasattr(self._layout_repo, "find_default"):
            default = self._layout_repo.find_default()
        if default is not None and getattr(default, "is_active", True):
            dto["resolved_layout_id"] = str(default.id)
            dto["resolved_layout_source"] = "default"
        else:
            dto["resolved_layout_id"] = None
            dto["resolved_layout_source"] = "none"
        return dto

    def _layout_is_seeded(self, layout_id: Any) -> bool:
        """True when the layout has ≥1 widget placement (cms_layout_widget row).

        A layout with zero placements is "not seeded" — it has no chrome and no
        content area, so a page using it renders blank; the public resolver
        treats it as unusable and falls back to the default layout. When no
        placement repo is wired we cannot tell, so we conservatively treat the
        explicit layout as usable (the disabled-feature path).
        """
        if self._layout_widget_repo is None:
            return True
        placements = self._layout_widget_repo.find_by_layout(str(layout_id))
        return bool(placements)

    def _with_term_ids(self, dto: Dict[str, Any], post_id: Any) -> Dict[str, Any]:
        """Attach the post's linked term ids so editors/lists can show the
        selected categories + tags (cms_post.to_dict has no term info).

        Also attaches ``pinned_term_ids`` — the subset of term ids whose link is
        pinned — so the editor can re-hydrate the per-category pin toggles on
        load (S-archives)."""
        links = self._post_term_repo.find_by_post(str(post_id))
        dto["term_ids"] = [str(link.term_id) for link in links]
        dto["pinned_term_ids"] = [
            str(link.term_id) for link in links if getattr(link, "pinned", False)
        ]
        return dto

    def _with_terms(self, dto: Dict[str, Any], post_id: Any) -> Dict[str, Any]:
        """Attach the post's linked terms as FULL term dicts (categories + tags)
        so the public renderer can show a tag cloud and real archive links. Each
        term dict carries an ``archive_url`` (the fixed ``category/``/``tag/``
        prefix map) so the fe never re-hardcodes the prefix. A link whose term no
        longer exists is skipped. Empty list when the post has no terms."""
        links = self._post_term_repo.find_by_post(str(post_id))
        terms: List[Dict[str, Any]] = []
        for link in links:
            term = self._term_repo.find_by_id(str(link.term_id))
            if term is not None:
                terms.append(self._term_dict_with_archive_url(term))
        dto["terms"] = terms
        return dto

    @staticmethod
    def _term_dict_with_archive_url(term: Any) -> Dict[str, Any]:
        """Serialize a term and append its archive URL (single-source map)."""
        term_dto = term.to_dict()
        term_dto["archive_url"] = term_archive_path(
            term_dto["term_type"], term_dto["slug"]
        )
        return term_dto

    def _primary_category_dict(self, post: Any) -> Optional[Dict[str, Any]]:
        """Return the post's primary category ``{slug, name, archive_url}`` or None.

        The primary is the explicit ``primary_term_id`` when it is set AND still
        resolves to a ``category`` term. Absent/dangling/non-category → ``None``
        (the card simply omits the eyebrow link). Additive; existing list
        payloads are unchanged apart from the new ``primary_category`` key.
        """
        primary_id = getattr(post, "primary_term_id", None)
        if not primary_id:
            return None
        term = self._term_repo.find_by_id(str(primary_id))
        if term is None or term.term_type != CATEGORY_TERM_TYPE:
            return None
        return {
            "slug": term.slug,
            "name": term.name,
            "archive_url": term_archive_path(term.term_type, term.slug),
        }

    def get_post(self, post_id: str) -> Dict[str, Any]:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")
        # Back-fill a preview token for posts that predate the column so the
        # editor always has a shareable preview URL.
        self._backfill_preview_token(post)
        return self._with_term_ids(self._with_resolved_style(post.to_dict()), post.id)

    def list_posts(
        self,
        post_type: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        language: Optional[str] = None,
        term_id: Optional[str] = None,
        layout_id: Optional[str] = None,
        style_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._repo.find_paginated(
            post_type=post_type,
            status=status,
            search=(search or None) and search.strip() or None,
            language=language or None,
            term_id=term_id or None,
            layout_id=layout_id or None,
            style_id=style_id or None,
            date_from=date_from or None,
            date_to=date_to or None,
            page=page,
            per_page=per_page,
            newest_first=newest_first,
            sort_by=sort_by,
            sort_dir=sort_dir,
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
        # Tags moved to the core catalog (D7): a ``tag`` filter resolves posts
        # via the core ``vbwd_entity_tag`` reverse index, not cms_post_term.
        # Categories (and any other term type) stay on the cms_term taxonomy.
        if term_type == TAG_TERM_TYPE:
            result = self._repo.find_by_tag_slug(
                tag_slug=term_slug,
                post_type=post_type,
                status=status,
                page=page,
                per_page=per_page,
                newest_first=newest_first,
            )
        else:
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

    def resolve_tag_term(self, slug: str) -> Optional[Dict[str, Any]]:
        """Resolve a TAG archive to a synthetic term dict, or ``None``.

        Tags live in the core ``vbwd_entity_tag`` index — NOT ``cms_term`` — so a
        tag has no stored term row. Validity is proxied by post existence via the
        SAME tag index the archive listing uses (``find_by_tag_slug``): a tag is
        valid iff at least one PUBLISHED post carries it, else ``None`` (so a
        genuinely unknown tag still 404s and falls through). The display name is
        the humanized slug (no core tag-catalog lookup — kept plugin-local).
        """
        normalized = slug.strip("/")
        result = self._repo.find_by_tag_slug(
            tag_slug=normalized,
            post_type=None,
            status=POST_STATUS_PUBLISHED,
            page=1,
            per_page=1,
        )
        if not result.get("total"):
            return None
        return {
            "term_type": TAG_TERM_TYPE,
            "slug": normalized,
            "name": humanize_term_slug(normalized),
            "description": None,
            "parent_id": None,
        }

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
        return self._with_terms(
            self._with_resolved_layout(self._with_resolved_style(post.to_dict())),
            post.id,
        )

    def _apply_content_blocks(self, post_id: Any, data: Dict[str, Any]) -> None:
        """Upsert any additional content areas carried in the payload (S55).

        ``content_blocks`` is a list of ``{area_name, content_html, source_css?,
        sort_order?, content_json?}``. The primary content area stays on
        ``content_html`` (SEO body) and is never written here. No-op when no
        content-block repo is wired or the key is absent.
        """
        if self._content_block_repo is None:
            return
        blocks = data.get("content_blocks")
        if not isinstance(blocks, list) or not blocks:
            return
        normalized = [block for block in blocks if block.get("area_name")]
        if normalized:
            self._content_block_repo.replace_for_post(str(post_id), normalized)

    # ── writes ───────────────────────────────────────────────────────────

    def create_post(self, data: Dict[str, Any]) -> Dict[str, Any]:
        post_type = (data.get("type") or "").strip()
        if not post_type_registry.is_registered(post_type):
            raise UnknownPostTypeError(f"Unknown post type '{post_type}'")

        title = (data.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        slug_base = (data.get("slug") or slugify(title)).strip("/")
        full_slug, primary_term_id = self._compute_full_slug(
            post_type=post_type, slug_base=slug_base, data=data, post=None
        )
        if self._is_permalink_engine(post_type):
            full_slug = self._unique_computed_slug(post_type, full_slug, post_id=None)
        elif self._repo.find_by_type_and_slug(post_type, full_slug):
            raise PostSlugConflictError(
                f"A '{post_type}' post with slug '{full_slug}' already exists"
            )

        parent_id = data.get("parent_id")
        if parent_id:
            self._validate_parent(post_type, parent_id, child_id=None)

        post = CmsPost()
        post.type = post_type
        post.slug = full_slug
        post.slug_base = slug_base
        post.primary_term_id = primary_term_id
        post.title = title
        post.excerpt = data.get("excerpt")
        post.featured_image_url = data.get("featured_image_url")
        post.source_css = data.get("source_css")
        post.content_json = data.get("content_json") or {}
        post.content_html = data.get("content_html")
        post.type_data = data.get("type_data")
        post.author_id = data.get("author_id")
        post.parent_id = parent_id
        post.status = data.get("status") or POST_STATUS_DRAFT
        post.language = data.get("language") or "en"
        post.translation_group_id = data.get("translation_group_id")
        post.sort_order = data.get("sort_order", 0)
        # Global blog-index pin (S-archives). Absent → False (unpinned), matching
        # the column default; existing create callers are unaffected.
        post.pinned = bool(data.get("pinned", False))
        self._apply_seo(post, data)
        self._apply_layout_style(post, data)
        if post.status == POST_STATUS_PUBLISHED and not post.published_at:
            post.published_at = datetime.now(timezone.utc)
        post.preview_token = uuid4().hex

        self._repo.save(post)
        self._apply_content_blocks(post.id, data)
        self._emit_content_changed(post, reason="created")
        return post.to_dict()

    def update_post(self, post_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")

        # Capture the pre-write slug so a rename can emit a 301 + carry
        # ``previous_slug`` for the SEO subscribers (prerender / cache / IndexNow).
        old_slug = post.slug

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
            "source_css",
            "type_data",
            "author_id",
            "language",
            "translation_group_id",
            "sort_order",
            # Global blog-index pin (S-archives). Round-trips like sort_order;
            # absent from the payload → left unchanged.
            "pinned",
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
        # validated transition as change_status so the state machine holds. Done
        # before the slug (re)compute so a publish-with-date materialises the
        # date-token segments of a computed permalink.
        status_changed = False
        if "status" in data and data["status"]:
            status_changed = self._transition_status(post, data["status"])

        # Slug (re)computation: engine posts re-render from slug_base + primary;
        # pages / mode-off keep the verbatim slug (today's behaviour + conflict).
        self._apply_slug_on_update(post, data)

        slug_changed = post.slug != old_slug
        if (
            slug_changed
            and post.type == "post"
            and post.status == POST_STATUS_PUBLISHED
        ):
            self._emit_slug_redirect(old_slug, post.slug)

        self._repo.save(post)
        self._apply_content_blocks(post.id, data)
        previous_slug = old_slug if slug_changed else None
        if (
            status_changed
            or slug_changed
            or any(field in data for field in _CONTENT_FIELDS)
        ):
            self._emit_content_changed(
                post, reason="updated", previous_slug=previous_slug
            )
        return post.to_dict()

    def _apply_slug_on_update(self, post: CmsPost, data: Dict[str, Any]) -> None:
        """Recompute + apply the slug on update.

        Engine posts (``type=post`` + mode≠off) re-render the full path from the
        post's own ``slug_base`` and its primary category, suffixing on collision.
        Everything else keeps the verbatim slug the editor supplied (today's
        behaviour), raising on a genuine conflict.
        """
        if self._is_permalink_engine(post.type):
            slug_base = self._effective_slug_base(data, post)
            full_slug, primary_term_id = self._compute_full_slug(
                post_type=post.type, slug_base=slug_base, data=data, post=post
            )
            full_slug = self._unique_computed_slug(
                post.type, full_slug, post_id=post.id
            )
            post.slug = full_slug
            post.slug_base = slug_base
            post.primary_term_id = primary_term_id
            return

        if "slug" in data:
            new_slug = (data["slug"] or "").strip("/")
            existing = self._repo.find_by_type_and_slug(post.type, new_slug)
            if existing and str(existing.id) != str(post.id):
                raise PostSlugConflictError(
                    f"A '{post.type}' post with slug '{new_slug}' already exists"
                )
            post.slug = new_slug
            post.slug_base = new_slug.rsplit("/", 1)[-1]
        if "primary_term_id" in data:
            post.primary_term_id = self._validated_term_id(data.get("primary_term_id"))

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

    def assign_terms(
        self,
        post_id: str,
        term_ids: List[str],
        pinned_term_ids: Optional[List[str]] = None,
    ) -> None:
        post = self._repo.find_by_id(post_id)
        if not post:
            raise PostNotFoundError(f"Post '{post_id}' not found")
        # ``pinned_term_ids`` (subset of ``term_ids``) flags the per-category pins.
        # ``None`` preserves the post's existing pins (legacy callers); an explicit
        # list is authoritative — the editor always sends it (S-archives).
        self._post_term_repo.replace_for_post(post_id, term_ids, pinned_term_ids)

    # ── bulk operations (admin list bulk-bar) ─────────────────────────────
    def bulk_delete(self, ids: List[str]) -> Dict[str, int]:
        return {"deleted": self._repo.bulk_delete(ids)}

    def bulk_set_status(self, ids: List[str], status: str) -> Dict[str, int]:
        """Publish/unpublish (or any transition) many posts. Posts whose current
        status can't legally move to ``status`` are skipped, not errored."""
        updated = 0
        for post in self._repo.find_by_ids(ids):
            try:
                changed = self._transition_status(post, status)
            except InvalidStatusTransitionError:
                continue
            if changed:
                self._repo.save(post)
                self._emit_content_changed(post, reason="status_changed")
                updated += 1
        return {"updated": updated}

    def bulk_set_searchable(self, ids: List[str], searchable: bool) -> Dict[str, int]:
        """Toggle search visibility for many posts (searchable ⇔ not excluded)."""
        posts = self._repo.find_by_ids(ids)
        for post in posts:
            post.seo_excluded = not searchable
            self._repo.save(post)
            self._emit_content_changed(post, reason="updated")
        return {"updated": len(posts)}

    def bulk_assign_term(self, ids: List[str], term_id: str) -> Dict[str, int]:
        """Add one term (e.g. a category) to many posts without dropping the
        terms they already carry."""
        updated = 0
        for post_id in ids:
            existing = [
                str(link.term_id)
                for link in self._post_term_repo.find_by_post(str(post_id))
            ]
            if term_id not in existing:
                existing.append(term_id)
                self._post_term_repo.replace_for_post(str(post_id), existing)
                updated += 1
        return {"updated": updated}

    def bulk_unassign_category(self, ids: List[str]) -> Dict[str, int]:
        """Remove every ``category``-type term from many posts, keeping any
        tags (or other term types) they carry.

        Mirrors ``bulk_assign_term`` (per-post junction edit via the term repo
        to resolve each term's type). Counts posts that actually changed.
        """
        updated = 0
        for post_id in ids:
            links = self._post_term_repo.find_by_post(str(post_id))
            remaining = [
                str(link.term_id)
                for link in links
                if not self._is_category_term(str(link.term_id))
            ]
            if len(remaining) != len(links):
                self._post_term_repo.replace_for_post(str(post_id), remaining)
                updated += 1
        return {"updated": updated}

    def _is_category_term(self, term_id: str) -> bool:
        term = self._term_repo.find_by_id(term_id)
        return term is not None and term.term_type == CATEGORY_TERM_TYPE

    # ── copy ("make a copy") ─────────────────────────────────────────────────

    def copy_post(self, post_id: str) -> Dict[str, Any]:
        """Duplicate one post (page or post) into a fresh DRAFT row.

        The copy never goes live: status=draft, published_at cleared, not pinned,
        a new preview token, and translation_group_id cleared (a copy is not a
        translation). Its slug is collision-safe ("<base>-copy", "-copy-2", …)
        within the same ``type`` (the (type, slug) uniqueness), and slug_base is
        recomputed from the new slug's tail. Author/parent/primary-term/layout/
        style/SEO/content all carry over. Owned children — content blocks,
        per-post widget placements, and term junction rows — are duplicated and
        re-pointed, keeping shared widget/term ids. Raises PostNotFoundError for
        an unknown id.
        """
        source = self._repo.find_by_id(post_id)
        if not source:
            raise PostNotFoundError(f"Post '{post_id}' not found")

        new_slug = self._copy_slug(source.type, source.slug)
        duplicate = CmsPost()
        duplicate.type = source.type
        duplicate.slug = new_slug
        duplicate.slug_base = new_slug.rsplit("/", 1)[-1]
        duplicate.primary_term_id = source.primary_term_id
        duplicate.title = f"{source.title} (Copy)"
        duplicate.excerpt = source.excerpt
        duplicate.featured_image_url = source.featured_image_url
        duplicate.content_json = deepcopy(source.content_json) or {}
        duplicate.content_html = source.content_html
        duplicate.source_css = source.source_css
        duplicate.type_data = deepcopy(source.type_data)
        duplicate.author_id = source.author_id
        duplicate.parent_id = source.parent_id
        # A copy is never live.
        duplicate.status = POST_STATUS_DRAFT
        duplicate.published_at = None
        duplicate.pinned = False
        duplicate.language = source.language
        # A copy is not a translation of the source.
        duplicate.translation_group_id = None
        duplicate.sort_order = source.sort_order
        duplicate.preview_token = uuid4().hex
        self._copy_seo_fields(source, duplicate)
        duplicate.layout_id = source.layout_id
        duplicate.style_id = source.style_id

        self._repo.save(duplicate)
        self._copy_post_children(str(source.id), str(duplicate.id))
        return duplicate.to_dict()

    def bulk_copy(self, ids: List[str]) -> Dict[str, Any]:
        """Copy many posts; unknown ids are skipped, not fatal."""
        items: List[Dict[str, Any]] = []
        for post_id in ids:
            try:
                items.append(self.copy_post(str(post_id)))
            except PostNotFoundError:
                continue
        return {"items": items, "count": len(items)}

    @staticmethod
    def _copy_seo_fields(source: CmsPost, duplicate: CmsPost) -> None:
        """Carry every SEO column onto the copy (schema_json deep-copied)."""
        duplicate.meta_title = source.meta_title
        duplicate.meta_description = source.meta_description
        duplicate.meta_keywords = source.meta_keywords
        duplicate.og_title = source.og_title
        duplicate.og_description = source.og_description
        duplicate.og_image_url = source.og_image_url
        duplicate.canonical_url = source.canonical_url
        duplicate.robots = source.robots
        duplicate.schema_json = deepcopy(source.schema_json)
        duplicate.seo_excluded = source.seo_excluded

    def _copy_post_children(self, source_id: str, target_id: str) -> None:
        """Duplicate a post's owned children onto the copy, re-pointing the
        parent FK and keeping shared widget/term ids untouched."""
        self._copy_content_blocks(source_id, target_id)
        self._copy_post_widgets(source_id, target_id)
        self._copy_post_terms(source_id, target_id)

    def _copy_content_blocks(self, source_id: str, target_id: str) -> None:
        if self._content_block_repo is None:
            return
        blocks = [
            {
                "area_name": block.area_name,
                "content_json": deepcopy(block.content_json),
                "content_html": block.content_html,
                "source_css": block.source_css,
                "sort_order": block.sort_order,
            }
            for block in self._content_block_repo.find_by_post(source_id)
        ]
        if blocks:
            self._content_block_repo.replace_for_post(target_id, blocks)

    def _copy_post_widgets(self, source_id: str, target_id: str) -> None:
        if self._post_widget_repo is None:
            return
        placements = [
            {
                "widget_id": str(placement.widget_id),
                "area_name": placement.area_name,
                "sort_order": placement.sort_order,
                "required_access_level_ids": placement.required_access_level_ids or [],
                "config_override": deepcopy(placement.config_override),
            }
            for placement in self._post_widget_repo.find_by_post(source_id)
        ]
        if placements:
            self._post_widget_repo.replace_for_post(target_id, placements)

    def _copy_post_terms(self, source_id: str, target_id: str) -> None:
        links = self._post_term_repo.find_by_post(source_id)
        term_ids = [str(link.term_id) for link in links]
        pinned_ids = [
            str(link.term_id) for link in links if getattr(link, "pinned", False)
        ]
        if term_ids:
            self._post_term_repo.replace_for_post(target_id, term_ids, pinned_ids)

    def _copy_slug(self, post_type: str, base_slug: str) -> str:
        """A free "<base>-copy" slug for ``post_type``, suffixing "-2"/"-3" on
        collision within the (type, slug) uniqueness scope."""
        return unique_slug(
            f"{base_slug}-copy",
            lambda candidate: self._repo.find_by_type_and_slug(post_type, candidate)
            is not None,
        )

    def bulk_assign_layout(
        self, ids: List[str], layout_id: Optional[str]
    ) -> Dict[str, int]:
        """Set one layout on many posts (e.g. all freshly imported pages), or
        clear it when ``layout_id`` is falsy (the bulk-"Unset layout" action).

        A non-empty layout_id is validated through the wired layout repo — an
        unknown layout raises InvalidLayoutOrStyleError, same as the single-post
        update path. A falsy layout_id sets ``layout_id = None`` without
        validation. Fires ``content.changed`` per post so the SEO prerender
        stays current.
        """
        self._resolve_themed_id(self._layout_repo, layout_id, "layout")
        posts = self._repo.find_by_ids(ids)
        for post in posts:
            post.layout_id = layout_id
            self._repo.save(post)
            self._emit_content_changed(post, reason="updated")
        return {"updated": len(posts)}

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

    def _backfill_preview_token(self, post: CmsPost) -> None:
        """Persist a preview token for a post that predates the column.

        Mirrors get_post's back-fill so imported/old posts surfaced by the
        admin lists always carry a shareable preview token.
        """
        if not post.preview_token:
            post.preview_token = uuid4().hex
            self._repo.save(post)

    def _serialize_page(self, result: Dict[str, Any]) -> Dict[str, Any]:
        posts = result.get("items", [])
        for item in posts:
            self._backfill_preview_token(item)
        dtos = [
            self._with_primary_category(
                self._with_term_ids(item.to_dict(), item.id), item
            )
            for item in posts
        ]
        self._attach_tags_bulk(dtos, posts)
        return {
            "items": dtos,
            "total": result.get("total", 0),
            "page": result.get("page", 1),
            "per_page": result.get("per_page", 20),
            "pages": result.get("pages", 1),
        }

    def _attach_tags_bulk(self, dtos: List[Dict[str, Any]], posts: List[Any]) -> None:
        """Attach each list item's core tags as ``{slug, name, archive_url}``.

        Efficient by construction: the page's post ids are grouped by core
        entity type and fetched with ONE ``get_tags_bulk`` query per type (at
        most two: ``cms_post`` + ``cms_page``) — never one query per post (no
        N+1). Every dto receives a ``tags`` list; a post with no tags — or a
        service with no tags port wired — gets ``[]`` (the disabled-feature
        path, so callers stay Liskov-safe).
        """
        for dto in dtos:
            dto["tags"] = []
        if self._tags_port is None or not posts:
            return
        ids_by_entity_type: Dict[str, List[UUID]] = {}
        for post in posts:
            entity_type = core_entity_type_for_post_type(getattr(post, "type", None))
            ids_by_entity_type.setdefault(entity_type, []).append(UUID(str(post.id)))
        slugs_by_id: Dict[UUID, List[str]] = {}
        for entity_type, entity_ids in ids_by_entity_type.items():
            slugs_by_id.update(self._tags_port.get_tags_bulk(entity_type, entity_ids))
        for dto, post in zip(dtos, posts):
            slugs = slugs_by_id.get(UUID(str(post.id)), [])
            dto["tags"] = [self._tag_chip(slug) for slug in slugs]

    @staticmethod
    def _tag_chip(slug: str) -> Dict[str, Any]:
        """A single tag rendered as the fe archive card expects it: the slug,
        a humanized display name, and the ``tag/<slug>`` archive path (via the
        single ``term_archive_path`` map — the fe never re-hardcodes the prefix).
        """
        return {
            "slug": slug,
            "name": humanize_term_slug(slug),
            "archive_url": term_archive_path(TAG_TERM_TYPE, slug),
        }

    def _with_primary_category(self, dto: Dict[str, Any], post: Any) -> Dict[str, Any]:
        """Attach the post's primary category (with archive URL) to a list item.

        Lets the fe archive card render a real ``/category/<slug>`` eyebrow link.
        ``None`` when the post has no resolvable primary category term.
        """
        dto["primary_category"] = self._primary_category_dict(post)
        return dto

    def _emit_content_changed(
        self, post: CmsPost, reason: str, previous_slug: Optional[str] = None
    ) -> None:
        if self._event_dispatcher is None:
            return
        payload: Dict[str, Any] = {
            "post_id": str(post.id),
            "type": post.type,
            "slug": post.slug,
            "status": post.status,
            "reason": reason,
        }
        # ``previous_slug`` is carried ONLY on a real rename (S122 §5a) so the SEO
        # subscribers can drop the orphaned prerender, invalidate the old render
        # cache, and re-ping IndexNow for the old URL. Absent on create and on any
        # save that did not move the slug — no spurious removals/submits.
        if previous_slug and previous_slug != post.slug:
            payload["previous_slug"] = previous_slug
        self._event_dispatcher.dispatch(Event(name=CONTENT_CHANGED_EVENT, data=payload))

    # ── permalink engine (S122) ──────────────────────────────────────────

    def preview_permalink(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute the ``{path, url}`` a post WOULD get, without persisting.

        Backs the admin live-preview endpoint so the editor reuses the exact
        backend renderer (DRY — no JS re-implementation).
        """
        post_type = (data.get("type") or "post").strip()
        title = (data.get("title") or "").strip()
        slug_base = (data.get("slug") or slugify(title)).strip("/")
        full_slug, _ = self._compute_full_slug(
            post_type=post_type, slug_base=slug_base, data=data, post=None
        )
        home_slug = self._permalink_config.get("home_slug")
        public_base_url = self._permalink_config.get("public_base_url", "")
        url = derive_canonical_url(None, full_slug, public_base_url, home_slug)
        return {"path": full_slug, "url": url}

    def _permalink_mode(self) -> str:
        return self._permalink_config.get("posts_permalink_mode") or PERMALINK_MODE_OFF

    def _is_permalink_engine(self, post_type: str) -> bool:
        """True when the permalink engine transforms this write (posts + mode on)."""
        return post_type == "post" and self._permalink_mode() != PERMALINK_MODE_OFF

    def _compute_full_slug(
        self,
        *,
        post_type: str,
        slug_base: str,
        data: Dict[str, Any],
        post: Optional[CmsPost],
    ) -> tuple:
        """Return ``(full_slug, primary_term_id)`` for a create/update/preview.

        Engine path: render the full path from ``slug_base`` + the resolved
        primary category. Non-engine path: the slug is verbatim ``slug_base`` and
        an explicitly-provided ``primary_term_id`` round-trips (never auto-picked).
        """
        assigned_ids = self._assigned_term_ids(data, post)
        if self._is_permalink_engine(post_type):
            primary_id = self._resolve_render_primary_id(data, assigned_ids, post)
            primary = self._primary_category_for(primary_id)
            published_at = (
                post.published_at
                if post is not None
                else _parse_datetime(data.get("published_at"))
            )
            rendered = self._renderer.render(
                self._permalink_mode(),
                self._permalink_config,
                slug_base=slug_base,
                primary_term=primary,
                published_at=published_at,
                post_id=str(post.id) if post is not None and post.id else None,
            )
            return (rendered or slug_base), primary_id

        if "primary_term_id" in data:
            return slug_base, self._validated_term_id(data.get("primary_term_id"))
        if post is not None and post.primary_term_id:
            return slug_base, str(post.primary_term_id)
        return slug_base, None

    def _assigned_term_ids(
        self, data: Dict[str, Any], post: Optional[CmsPost]
    ) -> List[str]:
        """The term ids assigned to the post — from the payload if present, else
        the persisted junction (an unsaved/new post has none)."""
        if "term_ids" in data and data["term_ids"] is not None:
            return [str(term_id) for term_id in data["term_ids"]]
        if post is not None and post.id is not None:
            return [
                str(link.term_id)
                for link in self._post_term_repo.find_by_post(str(post.id))
            ]
        return []

    def _resolve_render_primary_id(
        self,
        data: Dict[str, Any],
        assigned_ids: List[str],
        post: Optional[CmsPost],
    ) -> Optional[str]:
        """Primary-term precedence: explicit-among-assigned → existing-among-
        assigned → first assigned category → None."""
        if "primary_term_id" in data:
            explicit = data.get("primary_term_id")
            if explicit and str(explicit) in assigned_ids:
                return str(explicit)
        elif post is not None and post.primary_term_id:
            existing = str(post.primary_term_id)
            if existing in assigned_ids:
                return existing
        for term_id in assigned_ids:
            term = self._term_repo.find_by_id(term_id)
            if term is not None and term.term_type == CATEGORY_TERM_TYPE:
                return term_id
        return None

    @staticmethod
    def _validated_term_id(value: Any) -> Optional[str]:
        return str(value) if value else None

    def _primary_category_for(
        self, primary_id: Optional[str]
    ) -> Optional[PrimaryCategory]:
        if not primary_id:
            return None
        ancestor_slugs = self._term_ancestor_slugs(primary_id)
        if not ancestor_slugs:
            return None
        return PrimaryCategory(ancestor_slugs=tuple(ancestor_slugs))

    def _term_ancestor_slugs(self, primary_id: str) -> List[str]:
        """The primary term's slug chain root→leaf via ``parent_id`` walk."""
        slugs: List[str] = []
        seen: set = set()
        current = self._term_repo.find_by_id(str(primary_id))
        while current is not None and str(current.id) not in seen:
            slugs.append(current.slug)
            seen.add(str(current.id))
            parent_id = getattr(current, "parent_id", None)
            current = self._term_repo.find_by_id(str(parent_id)) if parent_id else None
        slugs.reverse()
        return slugs

    def _effective_slug_base(self, data: Dict[str, Any], post: CmsPost) -> str:
        """The post's own tail segment for a re-render: a supplied ``slug`` wins,
        else the stored ``slug_base``, else the last segment of the current slug
        (backfill for a post that predates the column)."""
        if "slug" in data:
            title = data.get("title", post.title)
            return (data["slug"] or slugify(title or "")).strip("/")
        if post.slug_base:
            return post.slug_base
        return (post.slug or "").rsplit("/", 1)[-1]

    def _unique_computed_slug(self, post_type: str, slug: str, post_id: Any) -> str:
        """Suffix ``-2``/``-3`` on a computed-slug collision (excluding self)."""

        def _exists(candidate: str) -> bool:
            found = self._repo.find_by_type_and_slug(post_type, candidate)
            return found is not None and (
                post_id is None or str(found.id) != str(post_id)
            )

        return unique_slug(slug, _exists)

    def _emit_slug_redirect(self, old_slug: str, new_slug: str) -> None:
        """Emit an idempotent 301 (old path_prefix → new target) on a rename."""
        if self._routing_rule_repo is None:
            return
        old_path = self._redirect_path(old_slug)
        target = self._redirect_path(new_slug)
        if old_path == target:
            return
        for rule in self._routing_rule_repo.find_by_match("path_prefix", old_path):
            if (
                getattr(rule, "target_slug", None) == target
                and getattr(rule, "redirect_code", None) == 301
            ):
                return
        rule = CmsRoutingRule()
        # Fixed short name — the old/new paths live in match_value/target_slug
        # (the ``name`` column is 120 chars and a nested path would overflow).
        rule.name = "Permalink rename 301"
        rule.match_type = "path_prefix"
        rule.match_value = old_path
        rule.target_slug = target
        rule.redirect_code = 301
        rule.is_rewrite = False
        rule.is_active = True
        rule.layer = "middleware"
        rule.priority = 0
        self._routing_rule_repo.save(rule)

    @staticmethod
    def _redirect_path(slug: Optional[str]) -> str:
        cleaned = (slug or "").strip("/")
        return "/" + cleaned if cleaned else "/"
