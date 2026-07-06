"""CmsRoutingMiddleware — Flask before_request hook for URL routing."""
import re
from typing import Any, Optional

from flask import request, redirect, Response, g


_PASSTHROUGH_PREFIXES = ("/api/", "/admin/", "/uploads/", "/_vbwd/")

# Core SEO endpoints (S47.1) are owned by core's seo blueprint and must never
# be rewritten/redirected by a cms routing rule, or robots/sitemap would 404.
_PASSTHROUGH_EXACT = ("/robots.txt", "/sitemap.xml")
_PASSTHROUGH_SITEMAP_CHUNK = "/sitemap-"

# IndexNow verification file, served at the site root by ``indexnow_key_file``
# (``cms_bp`` has no url_prefix). This MUST mirror the nginx location regex in
# ``vbwd-fe-user/nginx.prod.conf.template`` EXACTLY — 8-128 chars of
# ``[A-Za-z0-9-]`` then ``.txt`` — so a catch-all routing/geo rule can never
# shadow it. All matching ``<key>.txt`` paths pass through here; the route
# itself 404s any key that is not the configured one (exactly as nginx passes
# every candidate to the backend). ``/robots.txt`` (6 chars) does not match, so
# its explicit exact passthrough above still applies with no conflict.
_INDEXNOW_KEY_FILE_PATTERN = re.compile(r"^/[A-Za-z0-9-]{8,128}\.txt$")


def _is_passthrough(path: str) -> bool:
    if path in _PASSTHROUGH_EXACT:
        return True
    if path.startswith(_PASSTHROUGH_SITEMAP_CHUNK) and path.endswith(".xml"):
        return True
    if _INDEXNOW_KEY_FILE_PATTERN.match(path):
        return True
    return any(path.startswith(p) for p in _PASSTHROUGH_PREFIXES)


class CmsRoutingMiddleware:
    """Evaluates middleware-layer routing rules before each request."""

    def __init__(self, routing_service) -> None:
        self._service = routing_service

    def before_request(self) -> Optional[Any]:
        if _is_passthrough(request.path):
            return None
        from plugins.cms.src.services.routing.matchers import RequestContext

        ctx = RequestContext(
            path=request.path,
            accept_language=request.headers.get("Accept-Language", ""),
            remote_addr=request.remote_addr or "",
            geoip_country=g.get("geoip_country"),
            cookie_lang=request.cookies.get("vbwd_lang"),
        )
        instruction = self._service.evaluate(ctx)
        if instruction is None:
            return None
        if instruction.is_rewrite:
            resp = Response(status=200)
            resp.headers["X-Accel-Redirect"] = instruction.location
            return resp
        return redirect(instruction.location, code=instruction.code)
