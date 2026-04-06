"""CMS Pages plugin — pages, categories, and image gallery."""
from typing import Optional, Dict, Any, Union, TYPE_CHECKING
from vbwd.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint


DEFAULT_CONFIG = {
    "uploads_base_path": "/app/uploads",
    "uploads_base_url": "/uploads",
    "allowed_mime_types": [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "video/mp4",
    ],
    "max_file_size_bytes": 10 * 1024 * 1024,  # 10 MB
}


class CmsPlugin(BasePlugin):
    """CMS system: pages, categories, and image gallery.

    Class MUST be defined in __init__.py (not re-exported) due to
    discovery check obj.__module__ != full_module in manager.py.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="cms",
            version="1.0.0",
            author="VBWD Team",
            description="CMS Pages — manage content pages, categories, and media",
            dependencies=[],
        )

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        from plugins.cms.src.routes import cms_bp

        return cms_bp

    def get_url_prefix(self) -> Optional[str]:
        # Routes are defined with absolute paths — no prefix needed.
        return ""

    @property
    def admin_permissions(self):
        return [
            {"key": "cms.pages.view", "label": "View pages", "group": "CMS"},
            {"key": "cms.pages.manage", "label": "Manage pages", "group": "CMS"},
            {"key": "cms.images.view", "label": "View images", "group": "CMS"},
            {"key": "cms.images.manage", "label": "Manage images", "group": "CMS"},
            {"key": "cms.widgets.view", "label": "View widgets", "group": "CMS"},
            {"key": "cms.widgets.manage", "label": "Manage widgets", "group": "CMS"},
            {"key": "cms.layouts.manage", "label": "Manage layouts", "group": "CMS"},
            {"key": "cms.styles.manage", "label": "Manage styles", "group": "CMS"},
            {"key": "cms.configure", "label": "CMS settings", "group": "CMS"},
        ]

    def on_enable(self) -> None:
        import logging
        import os

        try:
            from flask import current_app
            from plugins.cms.src.middleware.routing_middleware import CmsRoutingMiddleware
            from plugins.cms.src.repositories.routing_rule_repository import (
                CmsRoutingRuleRepository,
            )
            from plugins.cms.src.services.routing.routing_service import CmsRoutingService
            from plugins.cms.src.services.routing.nginx_conf_generator import (
                NginxConfGenerator,
            )
            from plugins.cms.src.services.routing.nginx_reload_gateway import (
                StubNginxReloadGateway,
                SubprocessNginxReloadGateway,
            )
            from vbwd.extensions import db

            cfg = self._config or {}
            routing_cfg = cfg.get("routing", {})
            reload_cmd = routing_cfg.get("nginx_reload_command", "nginx -s reload")
            nginx_gw: Union[StubNginxReloadGateway, SubprocessNginxReloadGateway]
            if os.environ.get("TESTING") == "true":
                nginx_gw = StubNginxReloadGateway()
            else:
                nginx_gw = SubprocessNginxReloadGateway(reload_cmd)

            routing_svc = CmsRoutingService(
                rule_repo=CmsRoutingRuleRepository(db.session),
                conf_generator=NginxConfGenerator(),
                nginx_gateway=nginx_gw,
                config=cfg,
            )
            middleware = CmsRoutingMiddleware(routing_svc)
            current_app.before_request(middleware.before_request)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                f"CMS routing middleware not initialized: {exc}"
            )

    def on_disable(self) -> None:
        pass
