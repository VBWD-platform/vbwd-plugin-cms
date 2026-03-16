"""CmsRoutingMiddleware — Flask before_request hook for URL routing."""
from typing import Optional

from flask import request, redirect, Response, g


_PASSTHROUGH_PREFIXES = ("/api/", "/admin/", "/uploads/", "/_vbwd/")


def _is_passthrough(path: str) -> bool:
    return any(path.startswith(p) for p in _PASSTHROUGH_PREFIXES)


class CmsRoutingMiddleware:
    """Evaluates middleware-layer routing rules before each request."""

    def __init__(self, routing_service) -> None:
        self._service = routing_service

    def before_request(self) -> Optional[Response]:
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
