"""CMS plugin API routes.

Public endpoints:
    GET  /api/v1/cms/pages/<slug>
    GET  /api/v1/cms/pages            ?category=<slug>&page=1&per_page=20
    POST /api/v1/contact              contact form submission

Admin endpoints (require_admin):
    Pages:
        GET    /api/v1/admin/cms/pages
        POST   /api/v1/admin/cms/pages
        GET    /api/v1/admin/cms/pages/<id>
        PUT    /api/v1/admin/cms/pages/<id>
        DELETE /api/v1/admin/cms/pages/<id>
        POST   /api/v1/admin/cms/pages/bulk

    Categories:
        GET    /api/v1/admin/cms/categories
        POST   /api/v1/admin/cms/categories
        PUT    /api/v1/admin/cms/categories/<id>
        DELETE /api/v1/admin/cms/categories/<id>

    Images:
        GET    /api/v1/admin/cms/images
        POST   /api/v1/admin/cms/images/upload
        PUT    /api/v1/admin/cms/images/<id>
        POST   /api/v1/admin/cms/images/<id>/resize
        DELETE /api/v1/admin/cms/images/<id>
        POST   /api/v1/admin/cms/images/bulk
"""
import json
import logging
import mimetypes
from flask import (
    Blueprint,
    jsonify,
    request,
    current_app,
    send_from_directory,
    Response,
)

from vbwd.extensions import db
from vbwd.middleware.auth import require_auth, require_admin, require_permission

from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.repositories.cms_image_repository import CmsImageRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.cms_menu_item_repository import CmsMenuItemRepository
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.services.cms_page_service import (
    CmsPageService,
    CmsPageNotFoundError,
    CmsPageSlugConflictError,
)
from plugins.cms.src.services.cms_category_service import (
    CmsCategoryService,
    CmsCategoryConflictError,
)
from plugins.cms.src.services.cms_image_service import (
    CmsImageService,
    CmsImageNotFoundError,
)
from plugins.cms.src.services.cms_layout_service import (
    CmsLayoutService,
    CmsLayoutNotFoundError,
    CmsLayoutSlugConflictError,
)
from plugins.cms.src.services.cms_widget_service import (
    CmsWidgetService,
    CmsWidgetNotFoundError,
    CmsWidgetSlugConflictError,
    CmsWidgetInUseError,
)
from plugins.cms.src.services.cms_style_service import (
    CmsStyleService,
    CmsStyleNotFoundError,
    CmsStyleSlugConflictError,
)
from vbwd.interfaces.file_storage import ManagerBackedFileStorage
from plugins.cms.src.services.contact_form_service import (
    ContactFormService,
    HoneypotError,
    RateLimitError,
    ValidationError,
)
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.search_repository import SearchRepository
from plugins.cms.src.services.search_service import SearchService
from plugins.cms.src.services.post_service import (
    PostService,
    PostNotFoundError,
    PostSlugConflictError,
    UnknownPostTypeError,
    InvalidStatusTransitionError,
    PostHierarchyError,
    InvalidLayoutOrStyleError,
)
from plugins.cms.src.services.post_import_export_service import (
    PostImportExportService,
    PostImportError,
)
from plugins.cms.src.services.term_service import (
    TermService,
    TermNotFoundError,
    TermSlugConflictError,
    UnknownTermTypeError,
)
from plugins.cms.src.services.rss_feed_service import RssFeedService
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED, POST_STATUS_PRIVATE

# Some base images ship a mimetypes registry that does not know modern image
# formats (e.g. `.webp` → None → served as application/octet-stream, which an
# <img> cannot render). Register them explicitly so served uploads carry the
# correct Content-Type.
for _ext, _type in (
    (".webp", "image/webp"),
    (".avif", "image/avif"),
    (".svg", "image/svg+xml"),
):
    mimetypes.add_type(_type, _ext)

logger = logging.getLogger(__name__)

# Blueprint with no url_prefix — routes are defined with absolute paths.
cms_bp = Blueprint("cms", __name__)


# ── Access-level visibility helpers ──────────────────────────────────────────


def _get_current_user_access_level_ids() -> list[str]:
    """Get the current user's access level IDs from JWT, or ["new"] for anonymous.

    Does NOT require authentication — silently returns the "new" level slug
    when no valid token is present. Used for server-side content filtering.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return _get_new_level_ids()

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return _get_new_level_ids()

    try:
        from vbwd.services.auth_service import AuthService
        from vbwd.repositories.user_repository import UserRepository

        user_repo = UserRepository(db.session)
        auth_service = AuthService(user_repository=user_repo)
        user_id = auth_service.verify_token(parts[1])
        if not user_id:
            return _get_new_level_ids()

        user = user_repo.find_by_id(user_id)
        if not user:
            return _get_new_level_ids()

        levels = getattr(user, "assigned_user_access_levels", None)
        if levels:
            return [str(level.id) for level in levels]
        return _get_new_level_ids()
    except Exception:
        return _get_new_level_ids()


def _get_new_level_ids() -> list[str]:
    """Get the ID(s) of the 'new' user access level (anonymous fallback)."""
    try:
        from vbwd.models.user_access_level import UserAccessLevel

        level = db.session.query(UserAccessLevel).filter_by(slug="new").first()
        return [str(level.id)] if level else []
    except Exception:
        return []


def _filter_assignments_by_access(
    assignments: list[dict], user_level_ids: list[str]
) -> list[dict]:
    """Filter widget assignments based on user's access levels.

    Assignments with empty required_access_level_ids are visible to everyone.
    Others require the user to have at least one of the listed levels.
    """
    filtered = []
    for assignment in assignments:
        required = assignment.get("required_access_level_ids") or []
        if not required:
            filtered.append(assignment)
        elif any(level_id in required for level_id in user_level_ids):
            filtered.append(assignment)
    return filtered


def _enrich_assignments_with_widgets(assignments: list[dict]) -> list[dict]:
    """Attach full widget data to each assignment (DRY — used by page/post,
    public + admin). A failed widget lookup yields ``widget=None`` rather than
    breaking the whole payload."""
    if not assignments:
        return assignments
    widget_svc = _widget_service()
    for assignment in assignments:
        widget_id = assignment.get("widget_id")
        if widget_id:
            try:
                assignment["widget"] = widget_svc.get_widget(widget_id)
            except Exception:
                assignment["widget"] = None
    return assignments


def _post_content_blocks_dict(post_id: str) -> dict:
    """Return a post's additional content areas keyed by ``area_name`` (S55).

    Shape mirrors the legacy page enrichment: ``{area_name: {content_html,
    source_css, ...}}`` so the renderer can read ``contentBlocks[area]``.
    """
    blocks = _post_content_block_repo().find_by_post(post_id)
    return {block.area_name: block.to_dict() for block in blocks}


def _enrich_public_post_areas(post: dict) -> None:
    """Add ``content_blocks`` + access-filtered, enriched ``page_assignments``
    to a public post payload in place (S55 — mirror of /cms/pages/<slug>)."""
    post_id = post.get("id")
    if not post_id:
        return
    post["content_blocks"] = _post_content_blocks_dict(post_id)
    user_level_ids = _get_current_user_access_level_ids()
    assignments = [pw.to_dict() for pw in _post_widget_repo().find_by_post(post_id)]
    assignments = _filter_assignments_by_access(assignments, user_level_ids)
    post["page_assignments"] = _enrich_assignments_with_widgets(assignments)


# ── Service factory helpers ───────────────────────────────────────────────────


def _page_service() -> CmsPageService:
    page_repo = CmsPageRepository(db.session)
    cat_repo = CmsCategoryRepository(db.session)
    # style_repo wires the default-style resolver: pages without an explicit
    # style_id fall back to the admin-designated default (sprint 26).
    style_repo = CmsStyleRepository(db.session)
    return CmsPageService(page_repo, cat_repo, style_repo=style_repo)


def _category_service() -> CmsCategoryService:
    return CmsCategoryService(CmsCategoryRepository(db.session))


def _post_service() -> PostService:
    # content.changed is published onto the core EventBus (the plugin pub/sub
    # seam the 47.1 prerender writer subscribes to). ContentEventPublisher
    # exposes the ``.dispatch(Event)`` method PostService expects and forwards
    # to ``event_bus.publish``.
    from plugins.cms.src.services.content_event_publisher import (
        ContentEventPublisher,
    )

    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=ContentEventPublisher(),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
        content_block_repo=_post_content_block_repo(),
    )


def _term_service() -> TermService:
    return TermService(TermRepository(db.session))


def _post_import_export_service() -> PostImportExportService:
    return PostImportExportService(
        post_repo=PostRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        content_block_repo=_post_content_block_repo(),
        post_widget_repo=_post_widget_repo(),
        widget_repo=CmsWidgetRepository(db.session),
    )


def _search_service() -> SearchService:
    return SearchService(repo=SearchRepository(db.session))


def _rss_feed_service() -> RssFeedService:
    # Reuses the same PostService published-post query as the public lists; the
    # public_base_url / rss_item_limit come from the shared cms config.
    config = _cms_config()
    return RssFeedService(
        post_service=_post_service(),
        public_base_url=config.get("public_base_url", ""),
        item_limit=config.get("rss_item_limit", 20),
    )


def _post_is_publicly_visible(post: dict) -> bool:
    """Public reads expose published posts to anyone; private requires auth."""
    status = post.get("status")
    if status == POST_STATUS_PUBLISHED:
        return True
    if status == POST_STATUS_PRIVATE:
        return _is_authenticated_request()
    return False


def _is_authenticated_request() -> bool:
    """True when the request carries a valid bearer token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    try:
        from vbwd.services.auth_service import AuthService
        from vbwd.repositories.user_repository import UserRepository

        auth_service = AuthService(user_repository=UserRepository(db.session))
        return bool(auth_service.verify_token(parts[1]))
    except Exception:
        return False


def _image_service() -> CmsImageService:
    storage = ManagerBackedFileStorage(current_app.container.filesystem_manager())
    return CmsImageService(CmsImageRepository(db.session), storage)


def _page_widget_repo():
    from plugins.cms.src.repositories.cms_page_widget_repository import (
        CmsPageWidgetRepository,
    )

    return CmsPageWidgetRepository(db.session)


def _post_widget_repo():
    from plugins.cms.src.repositories.cms_post_widget_repository import (
        CmsPostWidgetRepository,
    )

    return CmsPostWidgetRepository(db.session)


def _post_content_block_repo():
    from plugins.cms.src.repositories.cms_post_content_block_repository import (
        CmsPostContentBlockRepository,
    )

    return CmsPostContentBlockRepository(db.session)


def _layout_service() -> CmsLayoutService:
    return CmsLayoutService(
        CmsLayoutRepository(db.session),
        CmsLayoutWidgetRepository(db.session),
        CmsWidgetRepository(db.session),
        CmsPageRepository(db.session),
    )


def _widget_service() -> CmsWidgetService:
    return CmsWidgetService(
        CmsWidgetRepository(db.session),
        CmsMenuItemRepository(db.session),
        CmsImageRepository(db.session),
        CmsLayoutWidgetRepository(db.session),
    )


def _style_service() -> CmsStyleService:
    return CmsStyleService(CmsStyleRepository(db.session))


def _cms_config() -> dict:
    config_store = getattr(current_app, "config_store", None)
    if config_store:
        cfg = config_store.get_config("cms")
        if cfg:
            return cfg
    return {
        "uploads_base_path": "/app/uploads",
        "uploads_base_url": "/uploads",
        "public_base_url": "",
        "rss_item_limit": 20,
    }


# ════════════════════════════════════════════════════════════════════════════
# CONTACT FORM — public POST endpoint
# ════════════════════════════════════════════════════════════════════════════

# Default recipient handle when the widget config names none.
_DEFAULT_MEINCHAT_RECIPIENTS = ["@admin"]


def build_meinchat_payload_block(config: dict) -> dict:
    """Project the widget's meinchat-delivery settings into the event block.

    cms stays agnostic of meinchat — it only copies these config keys so the
    (optional) meinchat plugin can read everything it needs straight off the
    ``contact_form.received`` event. Recipients default to ``["@admin"]``.
    """
    recipients = config.get("meinchat_recipients") or list(_DEFAULT_MEINCHAT_RECIPIENTS)
    return {
        "enabled": bool(config.get("meinchat_enabled", False)),
        "sender_email": (config.get("meinchat_sender_email") or "").strip(),
        "sender_nickname": (config.get("meinchat_sender_nickname") or "").strip(),
        "recipients": recipients,
    }


@cms_bp.route("/api/v1/contact", methods=["POST"])
def submit_contact_form():
    """Process a ContactForm widget submission.

    Body (JSON):
        widget_slug  – slug of the CMS widget (identifies config)
        fields       – dict of {field_id: value}
        _hp          – honeypot field (must be empty)

    Returns 200 on success, 404/422/429 on failure.
    """
    from vbwd.events.bus import event_bus
    from vbwd.utils.redis_client import redis_client

    body = request.get_json(silent=True) or {}
    widget_slug: str = str(body.get("widget_slug", "")).strip()

    if not widget_slug:
        return jsonify({"error": "widget_slug required"}), 422

    # Load widget config
    widget_repo = CmsWidgetRepository(db.session)
    widget = widget_repo.find_by_slug(widget_slug)
    if not widget:
        return jsonify({"error": "Form not found"}), 404

    if widget.widget_type != "vue-component":
        return jsonify({"error": "Form not found"}), 404

    config: dict = widget.config or {}
    if config.get("component_name") != "ContactForm":
        return jsonify({"error": "Form not found"}), 404

    recipient_email: str = (config.get("recipient_email") or "").strip()
    if not recipient_email:
        return jsonify({"error": "Contact form is not configured"}), 422

    svc = ContactFormService(redis_client)
    try:
        payload = svc.process_submission(
            config=config,
            form_data=body,
            remote_ip=request.remote_addr or "unknown",
        )
    except HoneypotError:
        # Silent reject — return OK so bots can't detect the honeypot
        return jsonify({"ok": True}), 200
    except RateLimitError:
        return jsonify({"error": "Too many requests. Please try again later."}), 429
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 422

    # S60 — enrich the event with the widget's meinchat-delivery settings so
    # the optional meinchat plugin can post the submission as a message. cms
    # has no runtime coupling to meinchat; the bridge is the event payload.
    payload["meinchat"] = build_meinchat_payload_block(config)
    # Source page/host for the message body (best-effort; never required).
    payload["source_url"] = request.headers.get("Referer", "")
    payload["source_host"] = request.host or ""

    event_bus.publish("contact_form.received", payload)
    logger.info(
        "[contact_form] Submitted widget=%s to=%s", widget_slug, recipient_email
    )
    return jsonify({"ok": True}), 200


# ════════════════════════════════════════════════════════════════════════════
# UPLOADS — serve uploaded media files
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename: str):
    """Serve uploaded files from the uploads directory.

    In production this is handled by nginx directly; in development
    Flask serves the files from the configured uploads_base_path.
    """
    config = _cms_config()
    uploads_dir = config.get("uploads_base_path", "/app/uploads")
    mime, _ = mimetypes.guess_type(filename)
    return send_from_directory(uploads_dir, filename, mimetype=mime or None)


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC — CMS pages (no auth required)
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/cms/categories", methods=["GET"])
def list_public_categories():
    """GET /api/v1/cms/categories — list all CMS categories (public)."""
    return jsonify(_category_service().list_categories()), 200


@cms_bp.route("/api/v1/cms/pages/<path:slug>", methods=["GET"])
def get_published_page(slug: str):
    """GET /api/v1/cms/pages/<slug> — fetch a published page by slug.

    Supports preview via ?preview_token=<token> for unpublished pages.
    Checks page-level access restrictions — returns 403 if user lacks required level.
    """
    preview_token = request.args.get("preview_token")
    try:
        if preview_token:
            page = _page_service().get_page(slug, published_only=False)
            if page.get("preview_token") != preview_token:
                return jsonify({"error": "Invalid preview token"}), 403
            return jsonify(page), 200

        page = _page_service().get_page(slug, published_only=True)

        # Check page-level access restriction
        required = page.get("required_access_level_ids") or []
        if required:
            user_level_ids = _get_current_user_access_level_ids()
            if not any(level_id in required for level_id in user_level_ids):
                return (
                    jsonify(
                        {
                            "error": "Access denied",
                            "required_access_levels": required,
                        }
                    ),
                    403,
                )

        # Include page-level widget assignments (filtered by access level)
        page_id = page.get("id")
        if page_id:
            user_level_ids = (
                user_level_ids
                if "user_level_ids" in dir()
                else _get_current_user_access_level_ids()
            )
            pw_repo = _page_widget_repo()
            page_widgets = [pw.to_dict() for pw in pw_repo.find_by_page(page_id)]
            page_widgets = _filter_assignments_by_access(page_widgets, user_level_ids)
            # Enrich with full widget data
            if page_widgets:
                widget_svc = _widget_service()
                for pw in page_widgets:
                    wid = pw.get("widget_id")
                    if wid:
                        try:
                            pw["widget"] = widget_svc.get_widget(wid)
                        except Exception:
                            pw["widget"] = None
            page["page_assignments"] = page_widgets

        return jsonify(page), 200
    except CmsPageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/cms/pages", methods=["GET"])
def list_published_pages():
    """GET /api/v1/cms/pages — list published pages, optionally filtered by category."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    filters = {}
    if request.args.get("category"):
        filters["category_slug"] = request.args.get("category")

    result = _page_service().list_pages(
        page=page, per_page=per_page, published_only=True, filters=filters
    )
    return jsonify(result), 200


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Pages
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/pages", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.pages.view")
def admin_list_pages():
    """GET /api/v1/admin/cms/pages — paginated list with filters."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    sort_by = request.args.get("sort_by", "updated_at")
    sort_dir = request.args.get("sort_dir", "desc")

    filters = {}
    if request.args.get("category_id"):
        filters["category_id"] = request.args.get("category_id")
    if request.args.get("language"):
        filters["language"] = request.args.get("language")
    if request.args.get("is_published") is not None:
        val = request.args.get("is_published", "").lower()
        if val in ("true", "1"):
            filters["is_published"] = True
        elif val in ("false", "0"):
            filters["is_published"] = False
    if request.args.get("search"):
        filters["search"] = request.args.get("search")

    result = _page_service().list_pages(
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filters=filters,
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/pages", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_create_page():
    """POST /api/v1/admin/cms/pages — create a new page."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        page = _page_service().create_page(data)
        return jsonify(page), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except CmsPageSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/pages/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_bulk_pages():
    """POST /api/v1/admin/cms/pages/bulk — bulk actions on pages.

    Body: {"ids": [...], "action": "publish|unpublish|delete|set_category",
           "params": {"category_id": "..."}}
    """
    data = request.get_json()
    if not data or "ids" not in data or "action" not in data:
        return jsonify({"error": "ids and action are required"}), 400
    try:
        result = _page_service().bulk_action(
            data["ids"], data["action"], data.get("params")
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cms_bp.route("/api/v1/admin/cms/pages/<page_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.pages.view")
def admin_get_page(page_id: str):
    """GET /api/v1/admin/cms/pages/<id> — get a single page (any publish state)."""
    svc = _page_service()
    # Find by ID, not slug
    page_obj = svc._repo.find_by_id(page_id)
    if not page_obj:
        return jsonify({"error": "Page not found"}), 404
    # Route through the service's default-style resolver so the admin UI
    # sees resolved_style_id / resolved_style_source — same as the public
    # /cms/pages/<slug> endpoint.
    result = svc._with_resolved_style(page_obj.to_dict())
    # Include page widget assignments
    pw_repo = _page_widget_repo()
    result["page_assignments"] = [pw.to_dict() for pw in pw_repo.find_by_page(page_id)]
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/pages/<page_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_update_page(page_id: str):
    """PUT /api/v1/admin/cms/pages/<id> — update a page."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        page = _page_service().update_page(page_id, data)
        return jsonify(page), 200
    except CmsPageNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, CmsPageSlugConflictError) as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/pages/<page_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_delete_page(page_id: str):
    """DELETE /api/v1/admin/cms/pages/<id> — delete a page."""
    try:
        _page_service().delete_page(page_id)
        return jsonify({"deleted": page_id}), 200
    except CmsPageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Page Widgets
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/pages/<page_id>/widgets", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.pages.view")
def admin_get_page_widgets(page_id: str):
    """GET /api/v1/admin/cms/pages/<id>/widgets — list page widget assignments."""
    pw_repo = _page_widget_repo()
    assignments = [pw.to_dict() for pw in pw_repo.find_by_page(page_id)]
    # Enrich with widget data
    if assignments:
        widget_svc = _widget_service()
        for assignment in assignments:
            wid = assignment.get("widget_id")
            if wid:
                try:
                    assignment["widget"] = widget_svc.get_widget(wid)
                except Exception:
                    assignment["widget"] = None
    return jsonify(assignments), 200


@cms_bp.route("/api/v1/admin/cms/pages/<page_id>/widgets", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_set_page_widgets(page_id: str):
    """PUT /api/v1/admin/cms/pages/<id>/widgets — replace page widget assignments."""
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "JSON array of assignments required"}), 400
    pw_repo = _page_widget_repo()
    created = pw_repo.replace_for_page(page_id, data)
    return jsonify([pw.to_dict() for pw in created]), 200


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Categories
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/categories", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.pages.view")
def admin_list_categories():
    """GET /api/v1/admin/cms/categories — list all categories."""
    return jsonify(_category_service().list_categories()), 200


@cms_bp.route("/api/v1/admin/cms/categories", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_create_category():
    """POST /api/v1/admin/cms/categories — create a category."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        cat = _category_service().create_category(data)
        return jsonify(cat), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cms_bp.route("/api/v1/admin/cms/categories/<cat_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_update_category(cat_id: str):
    """PUT /api/v1/admin/cms/categories/<id> — update a category."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        cat = _category_service().update_category(cat_id, data)
        return jsonify(cat), 200
    except KeyError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/categories/<cat_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_delete_category(cat_id: str):
    """DELETE /api/v1/admin/cms/categories/<id> — delete a category."""
    try:
        _category_service().delete_category(cat_id)
        return jsonify({"deleted": cat_id}), 200
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except CmsCategoryConflictError as e:
        return jsonify({"error": str(e)}), 409


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Images
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/images", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.images.view")
def admin_list_images():
    """GET /api/v1/admin/cms/images — paginated image list."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 24, type=int), 100)
    sort_by = request.args.get("sort_by", "created_at")
    sort_dir = request.args.get("sort_dir", "desc")
    search = request.args.get("search")

    result = _image_service().list_images(
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir,
        search=search,
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/images/upload", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.images.manage")
def admin_upload_image():
    """POST /api/v1/admin/cms/images/upload — upload an image (multipart/form-data)."""
    if "file" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    caption = request.form.get("caption")
    file_data = f.read()
    mime_type = f.content_type or "application/octet-stream"

    try:
        image = _image_service().upload_image(
            file_data=file_data,
            filename=f.filename,
            mime_type=mime_type,
            caption=caption,
        )
        return jsonify(image), 201
    except Exception as e:
        logger.error("Image upload failed: %s", e)
        return jsonify({"error": str(e)}), 500


@cms_bp.route("/api/v1/admin/cms/images/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.images.manage")
def admin_bulk_images():
    """POST /api/v1/admin/cms/images/bulk — bulk delete.

    Body: {"ids": [...], "action": "delete"}
    """
    data = request.get_json()
    if not data or "ids" not in data:
        return jsonify({"error": "ids required"}), 400

    action = data.get("action", "delete")
    if action != "delete":
        return jsonify({"error": f"Unknown action: {action}"}), 400

    result = _image_service().bulk_delete(data["ids"])
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/images/<image_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.images.manage")
def admin_update_image(image_id: str):
    """PUT /api/v1/admin/cms/images/<id> — update image caption/SEO."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        image = _image_service().update_image(image_id, data)
        return jsonify(image), 200
    except CmsImageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/images/<image_id>/resize", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.images.manage")
def admin_resize_image(image_id: str):
    """POST /api/v1/admin/cms/images/<id>/resize — resize an image.

    Body: {"width": 800, "height": 600}
    """
    data = request.get_json()
    if not data or "width" not in data or "height" not in data:
        return jsonify({"error": "width and height are required"}), 400
    try:
        image = _image_service().resize_image(image_id, data["width"], data["height"])
        return jsonify(image), 200
    except CmsImageNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@cms_bp.route("/api/v1/admin/cms/images/<image_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.images.manage")
def admin_delete_image(image_id: str):
    """DELETE /api/v1/admin/cms/images/<id> — delete an image and its file."""
    try:
        _image_service().delete_image(image_id)
        return jsonify({"deleted": image_id}), 200
    except CmsImageNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC — Layouts & Styles (no auth required)
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/cms/layouts/<layout_id>", methods=["GET"])
def get_layout_public(layout_id: str):
    """GET /api/v1/cms/layouts/<id> — layout with embedded widget data for fe-user.

    Filters widget assignments based on the requesting user's access levels.
    Anonymous visitors are treated as having the "new" access level.
    """
    try:
        layout = _layout_service().get_layout(layout_id)
        assignments = layout.get("assignments") or []

        # Filter by user access level
        user_level_ids = _get_current_user_access_level_ids()
        assignments = _filter_assignments_by_access(assignments, user_level_ids)

        # Enrich remaining assignments with full widget data
        if assignments:
            widget_svc = _widget_service()
            for a in assignments:
                wid = a.get("widget_id")
                if wid:
                    try:
                        a["widget"] = widget_svc.get_widget(wid)
                    except Exception:
                        a["widget"] = None
        layout["assignments"] = assignments
        return jsonify(layout), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/cms/layouts/by-slug/<slug>", methods=["GET"])
def get_layout_by_slug_public(slug: str):
    """GET /api/v1/cms/layouts/by-slug/<slug> — layout looked up by slug, widget data embedded.

    Filters widget assignments based on the requesting user's access levels.
    """
    try:
        layout = _layout_service().get_layout_by_slug(slug)
        assignments = layout.get("assignments") or []

        # Filter by user access level
        user_level_ids = _get_current_user_access_level_ids()
        assignments = _filter_assignments_by_access(assignments, user_level_ids)

        # Enrich remaining assignments with full widget data
        if assignments:
            widget_svc = _widget_service()
            for a in assignments:
                wid = a.get("widget_id")
                if wid:
                    try:
                        a["widget"] = widget_svc.get_widget(wid)
                    except Exception:
                        a["widget"] = None
        layout["assignments"] = assignments
        return jsonify(layout), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/cms/styles/<style_id>/css", methods=["GET"])
def get_style_css_public(style_id: str):
    """GET /api/v1/cms/styles/<id>/css — serve CSS as text/css."""
    try:
        css = _style_service().get_style_css(style_id)
        return Response(css, mimetype="text/css")
    except CmsStyleNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/cms/styles/default", methods=["GET"])
def get_default_style_public():
    """GET /api/v1/cms/styles/default — current default style or 404."""
    result = _style_service().get_default_style()
    if result is None:
        return jsonify({"error": "No default style configured"}), 404
    return jsonify(result), 200


@cms_bp.route("/api/v1/cms/styles/default/css", methods=["GET"])
def get_default_style_css_public():
    """GET /api/v1/cms/styles/default/css — CSS of the (active) default.

    404s when no default is set or the default is inactive.
    """
    css = _style_service().get_default_style_css()
    if css is None:
        return jsonify({"error": "No active default style"}), 404
    return Response(css, mimetype="text/css")


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Layouts
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/layouts", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_list_layouts():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    result = _layout_service().list_layouts(
        {
            "page": page,
            "per_page": per_page,
            "sort_by": request.args.get("sort_by", "sort_order"),
            "sort_dir": request.args.get("sort_dir", "asc"),
            "query": request.args.get("query"),
        }
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/layouts", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_create_layout():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        layout = _layout_service().create_layout(data)
        return jsonify(layout), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except CmsLayoutSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/layouts/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_bulk_layouts():
    data = request.get_json()
    if not data or "ids" not in data:
        return jsonify({"error": "ids required"}), 400
    result = _layout_service().bulk_delete(data["ids"])
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/layouts/bulk/active", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_bulk_layout_active():
    """POST /api/v1/admin/cms/layouts/bulk/active — activate/deactivate many."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or "active" not in data:
        return jsonify({"error": "ids array and active required"}), 400
    return jsonify(_layout_service().bulk_set_active(ids, bool(data["active"]))), 200


@cms_bp.route("/api/v1/admin/cms/layouts/<layout_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_get_layout(layout_id: str):
    try:
        return jsonify(_layout_service().get_layout(layout_id)), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/layouts/<layout_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_update_layout(layout_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_layout_service().update_layout(layout_id, data)), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, CmsLayoutSlugConflictError) as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/layouts/<layout_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_delete_layout(layout_id: str):
    try:
        _layout_service().delete_layout(layout_id)
        return jsonify({"deleted": layout_id}), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ── Default-layout management (mirrors the default-style routes) ─────────────


@cms_bp.route("/api/v1/admin/cms/layouts/default", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_clear_default_layout():
    """DELETE /api/v1/admin/cms/layouts/default — clear the default flag.

    Idempotent: returns 200 whether or not a default was set.
    """
    _layout_service().clear_default()
    return jsonify({"cleared": True}), 200


@cms_bp.route("/api/v1/admin/cms/layouts/<layout_id>/default", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_set_default_layout(layout_id: str):
    """POST /api/v1/admin/cms/layouts/<id>/default — promote to default.

    Demotes any existing default atomically.
    """
    try:
        return jsonify(_layout_service().set_default(layout_id)), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/layouts/<layout_id>/widgets", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_set_layout_widgets(layout_id: str):
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "JSON array of assignments required"}), 400
    try:
        result = _layout_service().set_widget_assignments(layout_id, data)
        return jsonify(result), 200
    except CmsLayoutNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Widgets
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/widgets", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.widgets.view")
def admin_list_widgets():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    result = _widget_service().list_widgets(
        {
            "page": page,
            "per_page": per_page,
            "sort_by": request.args.get("sort_by", "sort_order"),
            "sort_dir": request.args.get("sort_dir", "asc"),
            "query": request.args.get("query"),
            "widget_type": request.args.get("type"),
        }
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/widgets", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_create_widget():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        widget = _widget_service().create_widget(data)
        return jsonify(widget), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except CmsWidgetSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/widgets/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_bulk_widgets():
    data = request.get_json()
    if not data or "ids" not in data:
        return jsonify({"error": "ids required"}), 400
    result = _widget_service().bulk_delete(data["ids"])
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/widgets/<widget_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.widgets.view")
def admin_get_widget(widget_id: str):
    try:
        return jsonify(_widget_service().get_widget(widget_id)), 200
    except CmsWidgetNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/widgets/<widget_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_update_widget(widget_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_widget_service().update_widget(widget_id, data)), 200
    except CmsWidgetNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, CmsWidgetSlugConflictError) as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/widgets/<widget_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_delete_widget(widget_id: str):
    try:
        _widget_service().delete_widget(widget_id)
        return jsonify({"deleted": widget_id}), 200
    except CmsWidgetNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except CmsWidgetInUseError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/widgets/<widget_id>/menu", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_replace_widget_menu(widget_id: str):
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "JSON array of menu items required"}), 400
    try:
        result = _widget_service().replace_menu_tree(widget_id, data)
        return jsonify(result), 200
    except CmsWidgetNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — Styles
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/styles", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_list_styles():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    result = _style_service().list_styles(
        {
            "page": page,
            "per_page": per_page,
            "sort_by": request.args.get("sort_by", "sort_order"),
            "sort_dir": request.args.get("sort_dir", "asc"),
            "query": request.args.get("query"),
        }
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/styles", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_create_style():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        style = _style_service().create_style(data)
        return jsonify(style), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except CmsStyleSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/styles/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_bulk_styles():
    data = request.get_json()
    if not data or "ids" not in data:
        return jsonify({"error": "ids required"}), 400
    result = _style_service().bulk_delete(data["ids"])
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/styles/<style_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_get_style(style_id: str):
    try:
        return jsonify(_style_service().get_style(style_id)), 200
    except CmsStyleNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/styles/<style_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_update_style(style_id: str):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_style_service().update_style(style_id, data)), 200
    except CmsStyleNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except (ValueError, CmsStyleSlugConflictError) as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/styles/<style_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_delete_style(style_id: str):
    try:
        _style_service().delete_style(style_id)
        return jsonify({"deleted": style_id}), 200
    except CmsStyleNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ── Default-style management (sprint 26) ─────────────────────────────────────


@cms_bp.route("/api/v1/admin/cms/styles/default", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_clear_default_style():
    """DELETE /api/v1/admin/cms/styles/default — clear the default flag.

    Idempotent: returns 200 whether or not a default was set.
    """
    _style_service().clear_default()
    return jsonify({"cleared": True}), 200


@cms_bp.route("/api/v1/admin/cms/styles/<style_id>/default", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_set_default_style(style_id: str):
    """POST /api/v1/admin/cms/styles/<id>/default — promote to default.

    Demotes any existing default atomically.
    """
    try:
        return jsonify(_style_service().set_default(style_id)), 200
    except CmsStyleNotFoundError as e:
        return jsonify({"error": str(e)}), 404


# ════════════════════════════════════════════════════════════════════════════
# Routing Rules
# ════════════════════════════════════════════════════════════════════════════


def _routing_svc():
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )
    from plugins.cms.src.services.routing.routing_service import CmsRoutingService
    from plugins.cms.src.services.routing.nginx_conf_generator import NginxConfGenerator
    from plugins.cms.src.services.routing.nginx_reload_gateway import (
        StubNginxReloadGateway,
        SubprocessNginxReloadGateway,
    )
    import os

    cfg = _cms_config()
    routing_cfg = cfg.get("routing", {})
    reload_cmd = routing_cfg.get("nginx_reload_command", "nginx -s reload")
    if os.environ.get("TESTING") == "true":
        nginx_gw = StubNginxReloadGateway()
    else:
        nginx_gw = SubprocessNginxReloadGateway(reload_cmd)
    return CmsRoutingService(
        rule_repo=CmsRoutingRuleRepository(db.session),
        conf_generator=NginxConfGenerator(),
        nginx_gateway=nginx_gw,
        config=cfg,
    )


@cms_bp.route("/api/v1/cms/routing-rules", methods=["GET"])
def public_list_routing_rules():
    """GET /api/v1/cms/routing-rules — public, nginx-layer rules only."""
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )

    repo = CmsRoutingRuleRepository(db.session)
    rules = repo.find_all_active_for_layer("nginx")
    return jsonify([r.to_dict() for r in rules]), 200


@cms_bp.route("/api/v1/cms/routing-rules/middleware", methods=["GET"])
def public_list_middleware_routing_rules():
    """GET /api/v1/cms/routing-rules/middleware — public, middleware-layer rules only.
    Used by the fe-user SPA to resolve the homepage redirect client-side."""
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )

    repo = CmsRoutingRuleRepository(db.session)
    rules = repo.find_all_active_for_layer("middleware")
    return jsonify([r.to_dict() for r in rules]), 200


@cms_bp.route("/api/v1/admin/cms/routing-rules", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_list_routing_rules():
    """GET /api/v1/admin/cms/routing-rules — all rules ordered by priority."""
    return jsonify(_routing_svc().list_rules()), 200


@cms_bp.route("/api/v1/admin/cms/routing-rules", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_create_routing_rule():
    """POST /api/v1/admin/cms/routing-rules — create a new routing rule."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        rule = _routing_svc().create_rule(data)
        return jsonify(rule), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cms_bp.route("/api/v1/admin/cms/routing-rules/reload", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_reload_nginx():
    """POST /api/v1/admin/cms/routing-rules/reload — force nginx reload."""
    try:
        _routing_svc().sync_nginx()
        return jsonify({"status": "reloaded"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@cms_bp.route("/api/v1/admin/cms/routing-rules/<rule_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_get_routing_rule(rule_id: str):
    """GET /api/v1/admin/cms/routing-rules/<id> — get a single routing rule."""
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )

    repo = CmsRoutingRuleRepository(db.session)
    rule = repo.find_by_id(rule_id)
    if not rule:
        return jsonify({"error": "Routing rule not found"}), 404
    return jsonify(rule.to_dict()), 200


@cms_bp.route("/api/v1/admin/cms/routing-rules/<rule_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_update_routing_rule(rule_id: str):
    """PUT /api/v1/admin/cms/routing-rules/<id> — update a routing rule."""
    from plugins.cms.src.services.routing.routing_service import (
        CmsRoutingRuleNotFoundError,
    )

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        rule = _routing_svc().update_rule(rule_id, data)
        return jsonify(rule), 200
    except CmsRoutingRuleNotFoundError:
        return jsonify({"error": "Routing rule not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cms_bp.route("/api/v1/admin/cms/routing-rules/<rule_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.configure")
def admin_delete_routing_rule(rule_id: str):
    """DELETE /api/v1/admin/cms/routing-rules/<id> — delete (returns 204)."""
    from plugins.cms.src.services.routing.routing_service import (
        CmsRoutingRuleNotFoundError,
    )

    try:
        _routing_svc().delete_rule(rule_id)
        return "", 204
    except CmsRoutingRuleNotFoundError:
        return jsonify({"error": "Routing rule not found"}), 404


# ════════════════════════════════════════════════════════════════════════════
# S47.0 — Unified posts + terms (admin CRUD)
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/post-types", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_list_post_types():
    """GET /api/v1/admin/cms/post-types — registered post types."""
    return (
        jsonify(
            [
                {
                    "key": post_type.key,
                    "label": post_type.label,
                    "routable": post_type.routable,
                    "hierarchical": post_type.hierarchical,
                    "default_template": post_type.default_template,
                }
                for post_type in post_type_registry.list_post_types()
            ]
        ),
        200,
    )


@cms_bp.route("/api/v1/admin/cms/term-types", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_list_term_types():
    """GET /api/v1/admin/cms/term-types — registered term types."""
    return (
        jsonify(
            [
                {
                    "key": term_type.key,
                    "label": term_type.label,
                    "hierarchical": term_type.hierarchical,
                }
                for term_type in term_type_registry.list_term_types()
            ]
        ),
        200,
    )


@cms_bp.route("/api/v1/admin/cms/posts", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_list_posts():
    """GET /api/v1/admin/cms/posts — paginated list, any status."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    post_type = request.args.get("type")
    status = request.args.get("status")
    search = request.args.get("search")
    result = _post_service().list_posts(
        post_type=post_type,
        status=status,
        search=search,
        page=page,
        per_page=per_page,
        sort_by=request.args.get("sort_by"),
        sort_dir=request.args.get("sort_dir", "asc"),
        language=request.args.get("language"),
        term_id=request.args.get("category") or request.args.get("term_id"),
        layout_id=request.args.get("layout_id"),
        style_id=request.args.get("style_id"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/posts", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_create_post():
    """POST /api/v1/admin/cms/posts — create a post."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        post = _post_service().create_post(data)
        return jsonify(post), 201
    except UnknownPostTypeError as e:
        return jsonify({"error": str(e)}), 400
    except InvalidLayoutOrStyleError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except PostHierarchyError as e:
        return jsonify({"error": str(e)}), 422
    except PostSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_get_post(post_id: str):
    """GET /api/v1/admin/cms/posts/<id> — single post, any status.

    Includes ``content_blocks`` (additional content areas keyed by area_name)
    and ``page_assignments`` (the post's per-area widgets, enriched) so the
    editor can load existing values (S55).
    """
    try:
        result = _post_service().get_post(post_id)
    except PostNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    result["content_blocks"] = _post_content_blocks_dict(post_id)
    assignments = [pw.to_dict() for pw in _post_widget_repo().find_by_post(post_id)]
    result["page_assignments"] = _enrich_assignments_with_widgets(assignments)
    return jsonify(result), 200


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_update_post(post_id: str):
    """PUT /api/v1/admin/cms/posts/<id> — update a post."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_post_service().update_post(post_id, data)), 200
    except PostNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except InvalidLayoutOrStyleError as e:
        return jsonify({"error": str(e)}), 400
    except InvalidStatusTransitionError as e:
        return jsonify({"error": str(e)}), 422
    except PostHierarchyError as e:
        return jsonify({"error": str(e)}), 422
    except PostSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_delete_post(post_id: str):
    """DELETE /api/v1/admin/cms/posts/<id> — delete a post."""
    try:
        _post_service().delete_post(post_id)
        return jsonify({"deleted": post_id}), 200
    except PostNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>/widgets", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_get_post_widgets(post_id: str):
    """GET /api/v1/admin/cms/posts/<id>/widgets — list post widget assignments.

    Mirror of admin_get_page_widgets (S55). Each assignment is enriched with
    its full widget data so the editor can render the picker selection.
    """
    assignments = [pw.to_dict() for pw in _post_widget_repo().find_by_post(post_id)]
    return jsonify(_enrich_assignments_with_widgets(assignments)), 200


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>/widgets", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_set_post_widgets(post_id: str):
    """PUT /api/v1/admin/cms/posts/<id>/widgets — replace widget assignments.

    Body: a JSON array of ``{widget_id, area_name, sort_order,
    required_access_level_ids}``. Mirror of admin_set_page_widgets (S55).
    """
    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "JSON array of assignments required"}), 400
    created = _post_widget_repo().replace_for_post(post_id, data)
    return jsonify([pw.to_dict() for pw in created]), 200


@cms_bp.route("/api/v1/admin/cms/posts/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_posts():
    """POST /api/v1/admin/cms/posts/bulk — bulk delete by ids."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids array required"}), 400
    return jsonify(_post_service().bulk_delete(ids)), 200


@cms_bp.route("/api/v1/admin/cms/posts/bulk/status", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_post_status():
    """POST /api/v1/admin/cms/posts/bulk/status — publish/unpublish many."""
    data = request.get_json() or {}
    ids = data.get("ids")
    status = (data.get("status") or "").strip()
    if not isinstance(ids, list) or not status:
        return jsonify({"error": "ids array and status required"}), 400
    return jsonify(_post_service().bulk_set_status(ids, status)), 200


@cms_bp.route("/api/v1/admin/cms/posts/bulk/searchable", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_post_searchable():
    """POST /api/v1/admin/cms/posts/bulk/searchable — toggle search visibility."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or "searchable" not in data:
        return jsonify({"error": "ids array and searchable required"}), 400
    return (
        jsonify(_post_service().bulk_set_searchable(ids, bool(data["searchable"]))),
        200,
    )


@cms_bp.route("/api/v1/admin/cms/posts/bulk/assign-term", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_post_assign_term():
    """POST /api/v1/admin/cms/posts/bulk/assign-term — add a term to many."""
    data = request.get_json() or {}
    ids = data.get("ids")
    term_id = (data.get("term_id") or "").strip()
    if not isinstance(ids, list) or not term_id:
        return jsonify({"error": "ids array and term_id required"}), 400
    return jsonify(_post_service().bulk_assign_term(ids, term_id)), 200


@cms_bp.route("/api/v1/admin/cms/posts/bulk/assign-layout", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_post_assign_layout():
    """POST /api/v1/admin/cms/posts/bulk/assign-layout — set a layout on many,
    or clear it when ``layout_id`` is missing/null (the bulk-"Unset" action)."""
    data = request.get_json() or {}
    ids = data.get("ids")
    layout_id = (data.get("layout_id") or "").strip() or None
    if not isinstance(ids, list):
        return jsonify({"error": "ids array required"}), 400
    try:
        return jsonify(_post_service().bulk_assign_layout(ids, layout_id)), 200
    except InvalidLayoutOrStyleError as e:
        return jsonify({"error": str(e)}), 400


@cms_bp.route("/api/v1/admin/cms/posts/bulk/unassign-category", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_post_unassign_category():
    """POST /api/v1/admin/cms/posts/bulk/unassign-category — remove all
    category-type terms from many (keeps tags)."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids array required"}), 400
    return jsonify(_post_service().bulk_unassign_category(ids)), 200


@cms_bp.route("/api/v1/admin/cms/seo/regenerate", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_regenerate_seo():
    """POST /api/v1/admin/cms/seo/regenerate — rebuild the SEO prerender files.

    (Re)writes ``${VAR_DIR}/seo/<slug>.html`` for every published post — needed
    for content that predates the writer or arrived via a bulk backfill/import.
    Runs regardless of the ``seo_prerender_enabled`` toggle (manual override)
    and returns the number of files actually written.
    """
    from plugins.cms.src.services.seo_wiring import regenerate_prerendered

    count = regenerate_prerendered()
    return jsonify({"regenerated": count}), 200


@cms_bp.route("/api/v1/admin/cms/seo/cleanup", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_cleanup_seo():
    """POST /api/v1/admin/cms/seo/cleanup — delete all SEO prerender files.

    Removes every ``${VAR_DIR}/seo/*.html``. nginx serves prerendered pages by
    file existence, so after switching ``seo_prerender_enabled`` off this is how
    the stale static pages stop being served and traffic falls back to the SPA.
    """
    from plugins.cms.src.services.seo_wiring import purge_prerendered

    count = purge_prerendered()
    return jsonify({"removed": count}), 200


# The five admin-editable SEO settings (S56) stored in the cms config blob.
_SEO_SETTINGS_DEFAULTS = {
    "robots_txt": "",
    "sitemap_include_pages": True,
    "sitemap_excluded_slugs": [],
    "sitemap_include_terms": [],
    "sitemap_exclude_terms": [],
}


def _seo_settings_view(config: dict) -> dict:
    """Project the five SEO settings out of the full cms config (with defaults)."""
    return {
        key: config.get(key, default) for key, default in _SEO_SETTINGS_DEFAULTS.items()
    }


def _coerce_str_list(value) -> list:
    """Coerce a body value into a list of trimmed, non-empty strings."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _typed_seo_settings(body: dict) -> dict:
    """Validate/type the five SEO keys from the request body (ignore unknowns)."""
    typed: dict = {}
    if "robots_txt" in body:
        typed["robots_txt"] = str(body["robots_txt"] or "")
    if "sitemap_include_pages" in body:
        typed["sitemap_include_pages"] = bool(body["sitemap_include_pages"])
    for key in (
        "sitemap_excluded_slugs",
        "sitemap_include_terms",
        "sitemap_exclude_terms",
    ):
        if key in body:
            typed[key] = _coerce_str_list(body[key])
    return typed


@cms_bp.route("/api/v1/admin/cms/seo/settings", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_get_seo_settings():
    """GET /api/v1/admin/cms/seo/settings — the editable robots/sitemap config."""
    return jsonify(_seo_settings_view(_cms_config())), 200


@cms_bp.route("/api/v1/admin/cms/seo/settings", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_update_seo_settings():
    """PUT /api/v1/admin/cms/seo/settings — read-modify-write MERGE.

    ``save_config`` REPLACES the whole cms blob, so the typed SEO keys are
    merged into the FULL existing cms config (preserving ``seo_prerender_enabled``,
    ``uploads_base_path`` etc.); unknown body keys are ignored.
    """
    config_store = getattr(current_app, "config_store", None)
    if config_store is None:
        return jsonify({"error": "config store unavailable"}), 500
    body = request.get_json(silent=True) or {}
    config = config_store.get_config("cms") or {}
    config.update(_typed_seo_settings(body))
    config_store.save_config("cms", config)
    return jsonify(_seo_settings_view(config)), 200


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>/publish", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_publish_post(post_id: str):
    """POST /api/v1/admin/cms/posts/<id>/publish — move to published."""
    return _admin_change_post_status(post_id, POST_STATUS_PUBLISHED)


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>/unpublish", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_unpublish_post(post_id: str):
    """POST /api/v1/admin/cms/posts/<id>/unpublish — move back to draft."""
    return _admin_change_post_status(post_id, "draft")


def _admin_change_post_status(post_id: str, target_status: str):
    try:
        return jsonify(_post_service().change_status(post_id, target_status)), 200
    except PostNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except InvalidStatusTransitionError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/posts/<post_id>/terms", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_assign_post_terms(post_id: str):
    """PUT /api/v1/admin/cms/posts/<id>/terms — replace term links."""
    data = request.get_json()
    term_ids = (data or {}).get("term_ids")
    if not isinstance(term_ids, list):
        return jsonify({"error": "term_ids array required"}), 400
    try:
        _post_service().assign_terms(post_id, term_ids)
        return jsonify({"post_id": post_id, "term_ids": term_ids}), 200
    except PostNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/terms", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_list_terms():
    """GET /api/v1/admin/cms/terms?type= — terms of a type."""
    term_type = request.args.get("type")
    if not term_type:
        return jsonify({"error": "type query param required"}), 400
    return jsonify(_term_service().list_terms(term_type)), 200


@cms_bp.route("/api/v1/admin/cms/terms", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_create_term():
    """POST /api/v1/admin/cms/terms — create a term."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_term_service().create_term(data)), 201
    except UnknownTermTypeError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except TermSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/terms/<term_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_update_term(term_id: str):
    """PUT /api/v1/admin/cms/terms/<id> — update a term."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        return jsonify(_term_service().update_term(term_id, data)), 200
    except TermNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except TermSlugConflictError as e:
        return jsonify({"error": str(e)}), 409


@cms_bp.route("/api/v1/admin/cms/terms/<term_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_delete_term(term_id: str):
    """DELETE /api/v1/admin/cms/terms/<id> — delete a term."""
    try:
        _term_service().delete_term(term_id)
        return jsonify({"deleted": term_id}), 200
    except TermNotFoundError as e:
        return jsonify({"error": str(e)}), 404


@cms_bp.route("/api/v1/admin/cms/terms/bulk", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_bulk_terms():
    """POST /api/v1/admin/cms/terms/bulk — bulk delete by ids."""
    data = request.get_json() or {}
    ids = data.get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids array required"}), 400
    return jsonify(_term_service().bulk_delete(ids)), 200


@cms_bp.route("/api/v1/admin/cms/posts/export", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_export_posts():
    """GET /api/v1/admin/cms/posts/export?type= — posts as VBWD-standard JSON.

    Download-friendly: served as ``application/json`` with a ``Content-Disposition``
    attachment. Optional ``type`` query param scopes the export to one post-type.
    Layout/style/parent/term references are emitted as slugs (id-free) so the
    payload re-resolves on any target DB.
    """
    post_type = request.args.get("type") or None
    # Optional ``ids`` (comma-separated) scopes to "export selected".
    ids_param = request.args.get("ids")
    ids = [i for i in ids_param.split(",") if i] if ids_param else None
    payload = _post_import_export_service().export_posts(post_type=post_type, ids=ids)
    filename = f"cms-posts-{post_type}.json" if post_type else "cms-posts.json"
    return Response(
        json.dumps(payload, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@cms_bp.route("/api/v1/admin/cms/posts/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.manage")
def admin_import_posts():
    """POST /api/v1/admin/cms/posts/import — upsert posts from a VBWD-standard JSON.

    Body is the export envelope; returns ``{created, updated}``. Upsert is by the
    natural key ``(type, slug)`` and is idempotent; layout/style/parent/terms are
    resolved by slug on the target DB.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    try:
        result = _post_import_export_service().import_posts(data)
        return jsonify(result), 200
    except PostImportError as e:
        return jsonify({"error": str(e)}), 400


# ════════════════════════════════════════════════════════════════════════════
# S47.0 — Unified posts + terms (public read)
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/cms/posts", methods=["GET"])
def public_list_posts():
    """GET /api/v1/cms/posts — published posts, paginated, filterable."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    post_type = request.args.get("type")
    term_type = request.args.get("term_type")
    term_slug = request.args.get("term_slug")

    service = _post_service()
    if term_type and term_slug:
        result = service.list_posts_by_term(
            term_type=term_type,
            term_slug=term_slug,
            post_type=post_type,
            status=POST_STATUS_PUBLISHED,
            page=page,
            per_page=per_page,
        )
    else:
        result = service.list_posts(
            post_type=post_type,
            status=POST_STATUS_PUBLISHED,
            page=page,
            per_page=per_page,
        )
    return jsonify(result), 200


@cms_bp.route("/api/v1/cms/posts/<path:slug>", methods=["GET"])
def public_get_post(slug: str):
    """GET /api/v1/cms/posts/<path:slug>?type= — single post by path.

    Resolves nested page paths (e.g. ``about/team``) via the full-path slug.
    Published posts are public; private posts require an authorized session.
    A matching ``?preview_token=`` returns the post regardless of status, so an
    admin can preview a draft/pending/scheduled/private/trash post via a
    shareable link (the editor's "Preview" button).
    """
    post_type = request.args.get("type", "page")
    preview_token = request.args.get("preview_token")
    post = _post_service().resolve_published_path(post_type, slug)
    if not post:
        return jsonify({"error": "Post not found"}), 404
    _enrich_public_post_areas(post)
    if preview_token:
        if post.get("preview_token") and post["preview_token"] == preview_token:
            return jsonify(post), 200
        return jsonify({"error": "Invalid preview token"}), 403
    if not _post_is_publicly_visible(post):
        return jsonify({"error": "Post not found"}), 404
    return jsonify(post), 200


@cms_bp.route("/api/v1/cms/terms", methods=["GET"])
def public_list_terms():
    """GET /api/v1/cms/terms?type= — terms of a type."""
    term_type = request.args.get("type")
    if not term_type:
        return jsonify({"error": "type query param required"}), 400
    return jsonify(_term_service().list_terms(term_type)), 200


@cms_bp.route("/api/v1/cms/search", methods=["GET"])
def public_search_posts():
    """GET /api/v1/cms/search — full-text search over published posts (S47.4).

    Query params: ``q`` (search text), ``type`` (optional post type),
    ``term_type``+``term_slug`` (optional "search within category"),
    ``page``/``per_page``. Blank ``q`` yields an empty result, never all posts.
    Returns the same paginated summary shape as /cms/posts (so PostList reuses).
    """
    query = request.args.get("q", "")
    post_type = request.args.get("type")
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    term_type = request.args.get("term_type")
    term_slug = request.args.get("term_slug")
    term_filter = (term_type, term_slug) if term_type and term_slug else None

    result = _search_service().search(
        query,
        post_type=post_type,
        term_filter=term_filter,
        page=page,
        per_page=per_page,
    )
    return jsonify(result), 200


@cms_bp.route("/api/v1/cms/rss.xml", methods=["GET"])
def public_rss_feed():
    """GET /api/v1/cms/rss.xml — RSS 2.0 for the blog / a per-term archive.

    Query params: ``type`` (post type, default ``post``), ``term_type`` +
    ``term_slug`` (narrow to one taxonomy term). Reuses the shared published-post
    query (S47.0/47.4) — newest-first, capped at ``rss_item_limit``. An unknown
    term yields an empty but valid channel (never a 500).
    """
    post_type = request.args.get("type", "post")
    term_type = request.args.get("term_type")
    term_slug = request.args.get("term_slug")
    term = (term_type, term_slug) if term_type and term_slug else None

    xml = _rss_feed_service().build(post_type=post_type, term=term)
    return Response(xml, content_type="application/rss+xml; charset=utf-8")
