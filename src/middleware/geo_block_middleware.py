"""CmsGeoBlockMiddleware — before_request geo-block enforcement (S120).

Order of checks (a pure no-op when disabled):
1. Master switch off ⇒ pass.
2. Passthrough (never blocked): the routing middleware's passthrough set
   (``/api/``, ``/admin/``, ``/uploads/``, ``/_vbwd/``, robots/sitemap), static
   assets, AND the ``blocked_target_slug`` page + its sub-paths (loop-guard).
3. Bypass GET: if the request query carries the configured ``key=value``, mint a
   signed cookie and 302 to the same path with that param stripped.
4. Bypass cookie: a valid ``vbwd_geo_bypass`` cookie ⇒ pass.
5. Country gate: allowed ⇒ pass; unknown ⇒ pass unless ``block_unknown_country``;
   otherwise redirect to the locked slug (or 451 when the slug is empty).

Reuses ``routing_middleware._is_passthrough`` (DRY). Block responses are
``Cache-Control: private, no-store`` so a CDN/prerender never caches a block for
an allowed visitor (or vice-versa).
"""
import logging
from typing import Any, Optional
from urllib.parse import urlencode

from flask import Response, g, redirect, request

from plugins.cms.src.middleware.routing_middleware import _is_passthrough


logger = logging.getLogger(__name__)

BYPASS_COOKIE_NAME = "vbwd_geo_bypass"

# Static assets a locked-page SPA needs — never blocked (loop-guard). Extension
# match keeps extension-less CMS slugs (which SHOULD be blockable) out of it.
_STATIC_ASSET_EXTENSIONS = (
    ".js",
    ".mjs",
    ".css",
    ".map",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".json",
    ".mp4",
    ".webmanifest",
)


class CmsGeoBlockMiddleware:
    """Enforces the singleton geo-block config on every public request."""

    def __init__(self, service, token_signer, session=None) -> None:
        self._service = service
        self._token_signer = token_signer
        self._session = session

    def before_request(self) -> Optional[Any]:
        try:
            config = self._service.get_config_readonly()
        except Exception:
            # Fail open: geo-blocking is non-critical enforcement and must never
            # take down the whole API. A missing ``cms_geo_block_config`` table
            # (migration not yet applied) or any DB error simply means the gate
            # is not enforced for this request — allow it through.
            logger.warning(
                "Geo-block config unavailable; passing request through "
                "(geo-blocking not enforced)",
                exc_info=True,
            )
            # A failed query leaves the scoped session in an aborted transaction
            # (``InFailedSqlTransaction``). Every subsequent query in this same
            # request (currency lookup on ``/api/v1/config``, user lookup on
            # ``/api/v1/auth/login``) would then 500. Roll back to clear it so
            # the request can proceed. Guard the rollback itself: if it fails we
            # still pass through rather than propagate a new error.
            self._rollback_poisoned_transaction()
            return None

        if config is None or not config.is_enabled:
            return None

        path = request.path
        if self._is_passthrough(path, config.blocked_target_slug):
            return None

        bypass_response = self._maybe_start_bypass(config)
        if bypass_response is not None:
            return bypass_response

        if self._token_signer.verify(request.cookies.get(BYPASS_COOKIE_NAME)):
            return None

        country = g.get("geoip_country")
        if country:
            if country.upper() in self._service.allowed_codes():
                return None
        elif not config.block_unknown_country:
            return None

        return self._block_response(config)

    def _rollback_poisoned_transaction(self) -> None:
        if self._session is None:
            return
        try:
            self._session.rollback()
        except Exception:
            logger.warning(
                "Geo-block fail-open rollback failed; passing request through",
                exc_info=True,
            )

    # ── passthrough ───────────────────────────────────────────────────────────

    def _is_passthrough(self, path: str, blocked_target_slug: str) -> bool:
        if _is_passthrough(path):
            return True
        if self._is_static_asset(path):
            return True
        return self._is_locked_page(path, blocked_target_slug)

    @staticmethod
    def _is_static_asset(path: str) -> bool:
        return path.lower().endswith(_STATIC_ASSET_EXTENSIONS)

    @staticmethod
    def _is_locked_page(path: str, blocked_target_slug: str) -> bool:
        slug = (blocked_target_slug or "").rstrip("/")
        if not slug:
            return False
        return path == slug or path.startswith(slug + "/")

    # ── bypass GET → cookie ───────────────────────────────────────────────────

    def _maybe_start_bypass(self, config) -> Optional[Any]:
        bypass_query = config.bypass_query or ""
        if "=" not in bypass_query:
            return None
        key, _, value = bypass_query.partition("=")
        if request.args.get(key) != value:
            return None

        remaining = [
            (arg_key, arg_value)
            for arg_key, arg_value in request.args.items(multi=True)
            if arg_key != key
        ]
        query_string = urlencode(remaining)
        location = request.path + (f"?{query_string}" if query_string else "")

        response = redirect(location, code=302)
        response.set_cookie(
            BYPASS_COOKIE_NAME,
            self._token_signer.sign(config.bypass_cookie_ttl_days),
            max_age=config.bypass_cookie_ttl_days * 86400,
            secure=True,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return response

    # ── block ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _block_response(config) -> Any:
        slug = (config.blocked_target_slug or "").strip()
        if slug:
            response = redirect(slug, code=302)
        else:
            response = Response(
                "Access from your country is not permitted.",
                status=451,
                mimetype="text/plain",
            )
        response.headers["Cache-Control"] = "private, no-store"
        return response
