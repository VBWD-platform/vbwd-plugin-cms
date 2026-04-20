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
        POST   /api/v1/admin/cms/pages/export
        POST   /api/v1/admin/cms/pages/import

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
        GET    /api/v1/admin/cms/images/export
"""
import logging
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
from plugins.cms.src.services.file_storage import LocalFileStorage
from plugins.cms.src.services.contact_form_service import (
    ContactFormService,
    HoneypotError,
    RateLimitError,
    ValidationError,
)
from plugins.cms.src.services.cms_import_export_service import CmsImportExportService

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


def _image_service() -> CmsImageService:
    config = _cms_config()
    storage = LocalFileStorage(
        base_path=config.get("uploads_base_path", "/app/uploads"),
        base_url=config.get("uploads_base_url", "/uploads"),
    )
    return CmsImageService(CmsImageRepository(db.session), storage)


def _page_widget_repo():
    from plugins.cms.src.repositories.cms_page_widget_repository import (
        CmsPageWidgetRepository,
    )

    return CmsPageWidgetRepository(db.session)


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


def _import_export_service() -> CmsImportExportService:
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )

    config = _cms_config()
    storage = LocalFileStorage(
        base_path=config.get("uploads_base_path", "/app/uploads"),
        base_url=config.get("uploads_base_url", "/uploads"),
    )
    return CmsImportExportService(
        CmsCategoryRepository(db.session),
        CmsStyleRepository(db.session),
        CmsWidgetRepository(db.session),
        CmsLayoutRepository(db.session),
        CmsPageRepository(db.session),
        CmsRoutingRuleRepository(db.session),
        CmsImageRepository(db.session),
        CmsLayoutWidgetRepository(db.session),
        storage,
        pw_repo=_page_widget_repo(),
    )


def _cms_config() -> dict:
    config_store = getattr(current_app, "config_store", None)
    if config_store:
        cfg = config_store.get_config("cms")
        if cfg:
            return cfg
    return {
        "uploads_base_path": "/app/uploads",
        "uploads_base_url": "/uploads",
    }


# ════════════════════════════════════════════════════════════════════════════
# CONTACT FORM — public POST endpoint
# ════════════════════════════════════════════════════════════════════════════


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
    return send_from_directory(uploads_dir, filename)


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


@cms_bp.route("/api/v1/admin/cms/pages/export", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_export_pages():
    """POST /api/v1/admin/cms/pages/export — export pages as JSON.

    Body: {"ids": [...], "format": "json"}
    """
    from flask import Response

    data = request.get_json() or {}
    ids = data.get("ids", [])
    fmt = data.get("format", "json")

    payload = _page_service().export_pages(ids, fmt)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=cms-pages.json"},
    )


@cms_bp.route("/api/v1/admin/cms/pages/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_import_pages():
    """POST /api/v1/admin/cms/pages/import — import pages from JSON."""
    raw = request.get_data()
    if not raw:
        return jsonify({"error": "Request body required"}), 400
    try:
        result = _page_service().import_pages(raw)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Import failed: {e}"}), 400


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
    result = page_obj.to_dict()
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


@cms_bp.route("/api/v1/admin/cms/images/export", methods=["GET"])
@require_auth
@require_admin
@require_permission("cms.images.view")
def admin_export_images():
    """GET /api/v1/admin/cms/images/export?ids=id1,id2 — export ZIP of selected images."""
    from flask import Response

    ids_param = request.args.get("ids", "")
    ids = [i.strip() for i in ids_param.split(",") if i.strip()]
    if not ids:
        return jsonify({"error": "ids query parameter required"}), 400

    payload = _image_service().export_zip(ids)
    return Response(
        payload,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=cms-images.zip"},
    )


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


@cms_bp.route("/api/v1/admin/cms/layouts/export", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_export_layouts():
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if len(ids) == 1:
        payload = _layout_service().export_layout(ids[0])
        import json as _json

        return Response(
            _json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=cms-layout.json"},
        )
    payload = _layout_service().export_layouts_zip(ids)
    return Response(
        payload,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=cms-layouts.zip"},
    )


@cms_bp.route("/api/v1/admin/cms/layouts/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.layouts.manage")
def admin_import_layouts():
    import json as _json

    raw = request.get_data()
    if not raw:
        return jsonify({"error": "Request body required"}), 400
    try:
        payload = _json.loads(raw)
        result = _layout_service().import_layout(payload)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Import failed: {e}"}), 400


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


@cms_bp.route("/api/v1/admin/cms/widgets/export", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_export_widgets():
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if len(ids) == 1:
        payload = _widget_service().export_widget(ids[0])
        import json as _json

        return Response(
            _json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=cms-widget.json"},
        )
    payload = _widget_service().export_widgets_zip(ids)
    return Response(
        payload,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=cms-widgets.zip"},
    )


@cms_bp.route("/api/v1/admin/cms/widgets/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.widgets.manage")
def admin_import_widgets():
    import json as _json

    raw = request.get_data()
    if not raw:
        return jsonify({"error": "Request body required"}), 400
    try:
        payload = _json.loads(raw)
        data = payload.get("data", payload)
        result = _widget_service().import_widget(data)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Import failed: {e}"}), 400


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


@cms_bp.route("/api/v1/admin/cms/styles/export", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_export_styles():
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if len(ids) == 1:
        payload = _style_service().export_style(ids[0])
        import json as _json

        return Response(
            _json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=cms-style.json"},
        )
    payload = _style_service().export_styles_zip(ids)
    return Response(
        payload,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=cms-styles.zip"},
    )


@cms_bp.route("/api/v1/admin/cms/styles/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.styles.manage")
def admin_import_styles():
    import json as _json

    raw = request.get_data()
    if not raw:
        return jsonify({"error": "Request body required"}), 400
    try:
        payload = _json.loads(raw)
        data = payload.get("data", payload)
        result = _style_service().import_style(data)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": f"Import failed: {e}"}), 400


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
# CMS IMPORT / EXPORT
# ════════════════════════════════════════════════════════════════════════════


@cms_bp.route("/api/v1/admin/cms/export", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_cms_export():
    """POST /api/v1/admin/cms/export — export CMS content as a ZIP.

    Body (JSON):
        sections  – list of section names, or ["everything"]
                    e.g. ["pages", "widgets", "categories"]
    Returns:
        ZIP binary (application/zip)
    """
    data = request.get_json(silent=True) or {}
    sections = data.get("sections", ["everything"])
    try:
        zip_bytes = _import_export_service().export(sections)
    except Exception as e:
        logger.exception("CMS export failed")
        return jsonify({"error": str(e)}), 500
    return Response(
        zip_bytes,
        status=200,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=cms-export.zip"},
    )


@cms_bp.route("/api/v1/admin/cms/import", methods=["POST"])
@require_auth
@require_admin
@require_permission("cms.pages.manage")
def admin_cms_import():
    """POST /api/v1/admin/cms/import — import CMS content from a ZIP.

    Multipart form fields:
        file      – the ZIP file
        strategy  – "add" | "index" | "drop_all"
    Returns:
        JSON { imported: {...}, errors: [...] }
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400
    strategy = request.form.get("strategy", "add")
    if strategy not in ("add", "index", "drop_all"):
        return jsonify({"error": "Invalid strategy"}), 400
    try:
        result = _import_export_service().import_zip(file.read(), strategy)
    except Exception as e:
        logger.exception("CMS import failed")
        return jsonify({"error": str(e)}), 500
    return jsonify(result), 200
