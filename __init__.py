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
    "posts_per_page": 20,
    "scheduled_publish_interval_seconds": 60,
    # Absolute site root for RSS channel links + the per-item fallback
    # permalink (S47.5). Item links prefer the post's stored canonical_url —
    # the same absolute URL SEO canonical / sitemap use — and only fall back
    # to "<public_base_url>/<slug>" when a post has no canonical URL.
    "public_base_url": "",
    "rss_item_limit": 20,
    # When on, content changes write prerendered SEO HTML to ${VAR_DIR}/seo/
    # for crawlers; when off the app serves the SPA only (no prerender). The
    # SEO pipeline is still wired on enable — the toggle is read live per
    # content change, so flipping it takes effect without re-enabling.
    "seo_prerender_enabled": True,
    # Base URL of an external full-page renderer. When set, the prerender
    # writer POSTs {slug, language} to "<url>/prerender" and saves the
    # COMPLETE page HTML (layout + content) it returns; empty ⇒ off (the
    # writer keeps its content-only document — current behaviour).
    "prerender_service_url": "",
    # Admin-editable robots.txt body (S56). Empty ⇒ the default template the
    # robots() route builds; a non-empty string is served verbatim. seo.mode=off
    # still forces "Disallow: /" (safety wins).
    "robots_txt": "",
    # Sitemap.xml filtering (S56), all read live per request. When
    # sitemap_include_pages is False, type=="page" posts are dropped;
    # sitemap_excluded_slugs drops posts by slug; sitemap_include_terms (term
    # slugs) — when non-empty — restricts to posts carrying ≥1; and
    # sitemap_exclude_terms (term slugs) drops posts carrying any.
    "sitemap_include_pages": True,
    "sitemap_excluded_slugs": [],
    "sitemap_include_terms": [],
    "sitemap_exclude_terms": [],
    "debug_mode": False,
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

        # Attach the root-level SEO routes (/sitemap.xml, /sitemap-<n>.xml,
        # /robots.txt) onto cms_bp; importing the module registers them.
        from plugins.cms.src import seo_routes

        assert seo_routes.cms_bp is cms_bp
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
            {"key": "cms.manage", "label": "Manage content", "group": "CMS"},
        ]

    @property
    def api_scopes(self):
        """API-key scopes this plugin's endpoints require (S52).

        Read by the core ``api_scope_registry`` (never imported by core).
        ``user_grantable`` lets a user self-grant this scope on the Manage-API
        page; admins may grant any registered scope.
        """
        return [
            {
                "key": "cms:posts:create",
                "label": "Create CMS posts/pages",
                "description": "Create a post or page via the content-ingestion API.",
                "user_grantable": True,
            }
        ]

    def _register_built_in_types(self) -> None:
        """Register the built-in post-types and term-types (S47.0).

        cms ships ``page`` (hierarchical) + ``post`` (flat) and the
        ``category`` (hierarchical) + ``tag`` (flat) taxonomies. Other
        plugins register more via the same registries with zero cms change.
        """
        from plugins.cms.src.services.post_type_registry import (
            PostType,
            register_post_type,
        )
        from plugins.cms.src.services.term_type_registry import (
            TermType,
            register_term_type,
        )

        register_post_type(
            PostType(key="page", label="Page", routable=True, hierarchical=True)
        )
        register_post_type(
            PostType(key="post", label="Post", routable=True, hierarchical=False)
        )
        register_term_type(
            TermType(key="category", label="Category", hierarchical=True)
        )
        # Tags are no longer a cms_term taxonomy (D7): they live in the single
        # core tag catalog (``vbwd_tag``), managed under Settings → Custom
        # Fields → Global tags. So the ``tag`` term type is deliberately NOT
        # registered — TermManager.vue (tabs come from this registry) loses its
        # "Tag" tab automatically, leaving category management intact.

    def _register_unified_repositories(self) -> None:
        """Register the S47.0 repos as DI providers on the container.

        Core declares none of these (new in cms), so the plugin must add
        them — routes/services resolve them via the shared container, the
        same pattern the subscription plugin uses for its extracted repos.
        """
        from flask import current_app

        container = getattr(current_app, "container", None)
        if not container:
            return
        from dependency_injector import providers
        from plugins.cms.src.repositories.post_repository import PostRepository
        from plugins.cms.src.repositories.term_repository import TermRepository
        from plugins.cms.src.repositories.post_term_repository import (
            PostTermRepository,
        )

        container.cms_post_repository = providers.Factory(
            PostRepository, session=container.db_session
        )
        container.cms_term_repository = providers.Factory(
            TermRepository, session=container.db_session
        )
        container.cms_post_term_repository = providers.Factory(
            PostTermRepository, session=container.db_session
        )

    def _register_seo_pipeline(self) -> None:
        """Wire the S47.1 SEO pipeline (prerender subscriber + sitemap provider).

        The prerender writer subscribes to ``content.changed`` on the EventBus
        and the cms sitemap provider is registered with the core sitemap
        registry. Core declares neither — both are cms-owned (agnostic seam).
        """
        import logging

        try:
            from plugins.cms.src.services.seo_wiring import register_seo_pipeline

            register_seo_pipeline()
        except Exception as seo_error:
            logging.getLogger(__name__).warning(
                "[cms] Failed to register SEO pipeline: %s", seo_error
            )

    def _register_cli_commands(self) -> None:
        """Register the plugin's ``flask cms ...`` CLI group.

        Core declares no cms command (it stays agnostic); the plugin adds its
        group to the live app's click group on enable. Guarded so a repeat
        enable (e.g. per-test app) does not raise on a duplicate name.
        """
        import logging
        from flask import current_app

        try:
            from plugins.cms.src.cli import cms_cli

            if "cms" not in current_app.cli.commands:
                current_app.cli.add_command(cms_cli)
        except Exception as cli_error:
            logging.getLogger(__name__).warning(
                "[cms] Failed to register CLI commands: %s", cli_error
            )

    def _start_scheduled_publish_tick(self) -> None:
        """Start the scheduled-publish tick — never under TESTING.

        Each test builds its own app and runs on_enable; an unguarded
        scheduler would leak a thread (and DB work) per test app. Core and
        the subscription plugin guard their schedulers the same way.
        """
        import logging
        from flask import current_app

        if current_app.config.get("TESTING"):
            return
        try:
            from plugins.cms.src.services.scheduled_publish import (
                start_scheduled_publish_tick,
            )

            cfg = self._config or {}
            interval = cfg.get("scheduled_publish_interval_seconds", 60)
            start_scheduled_publish_tick(current_app._get_current_object(), interval)
        except Exception as scheduler_error:
            logging.getLogger(__name__).warning(
                "[cms] Failed to start scheduled-publish tick: %s", scheduler_error
            )

    def _register_data_exchangers(self) -> None:
        """Register the CMS entity exchangers into the core data-exchange seam.

        Core declares none of these (it stays agnostic); the plugin adds them on
        enable through the shared ``db.session`` + the gallery file storage, so
        CMS entities appear on the generic Settings → Import/Export page and the
        per-list controls — coexisting with the bespoke ``/admin/cms/*`` routes.
        Clear-safe: re-registering replaces by key (per-test app re-enable).
        """
        import logging

        try:
            from flask import current_app
            from vbwd.extensions import db
            from vbwd.interfaces.file_storage import ManagerBackedFileStorage
            from plugins.cms.src.services.data_exchange.cms_exchangers import (
                register_cms_exchangers,
            )

            storage = ManagerBackedFileStorage(
                current_app.container.filesystem_manager()
            )
            register_cms_exchangers(db.session, file_storage=storage)
        except Exception as exchanger_error:
            logging.getLogger(__name__).warning(
                "[cms] Failed to register data exchangers: %s", exchanger_error
            )

    def _register_demo_seed_hooks(self) -> None:
        """Contribute CMS seed + backfill to ``flask reset-demo`` (S88).

        ``seed_catalog`` runs with the other catalog seeders; ``run_backfill``
        runs as a post-seed hook so it folds EVERY plugin's seeded pages into
        the unified model after they all exist. Core imports no cms model.
        """
        from vbwd.services.demo_data_registry import (
            register_catalog_seeder,
            register_post_seed_hook,
        )
        from plugins.cms.src.demo_seed import run_backfill, seed_catalog

        register_catalog_seeder(seed_catalog)
        register_post_seed_hook(run_backfill)

    def _register_entity_types(self) -> None:
        """Register cms_page / cms_post as taggable/custom-field-able (S77).

        The unified ``cms_post`` table holds both pages (``type=page``) and posts
        (``type=post``); the new core tags/custom-fields blocks are keyed off
        that discriminator (page → ``cms_page``, post → ``cms_post``) and live
        ALONGSIDE the existing CMS ``terms`` taxonomy (categories + legacy tag
        terms), which is untouched (the D7 tag migration is a later slice).
        """
        from vbwd.services.entity_type_registry import (
            EntityTypeRegistration,
            register_entity_type,
        )

        register_entity_type(
            EntityTypeRegistration("cms_page", "Page", "cms.pages.manage")
        )
        register_entity_type(EntityTypeRegistration("cms_post", "Post", "cms.manage"))

    def on_enable(self) -> None:
        import logging
        import os

        self._register_built_in_types()
        self._register_unified_repositories()
        self._register_cli_commands()
        self._start_scheduled_publish_tick()
        self._register_seo_pipeline()
        self._register_data_exchangers()
        self._register_demo_seed_hooks()
        self._register_entity_types()

        # Register the access-level content provider (S01). This lets core's
        # /admin/access/user-levels/<id>/content route discover CMS-restricted
        # pages and widgets through the IAccessLevelContentProvider port
        # instead of importing CMS models directly.
        from vbwd.services.access_level_content_provider import (
            register_access_level_content_provider,
        )
        from plugins.cms.src.services.access_content_provider import (
            CmsAccessContentProvider,
        )

        register_access_level_content_provider(CmsAccessContentProvider())

        try:
            from flask import current_app
            from plugins.cms.src.middleware.routing_middleware import (
                CmsRoutingMiddleware,
            )
            from plugins.cms.src.repositories.routing_rule_repository import (
                CmsRoutingRuleRepository,
            )
            from plugins.cms.src.services.routing.routing_service import (
                CmsRoutingService,
            )
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
        import logging

        from vbwd.services.access_level_content_provider import (
            clear_access_level_content_providers,
        )
        from vbwd.services.entity_type_registry import unregister_entity_type

        unregister_entity_type("cms_page")
        unregister_entity_type("cms_post")

        try:
            from plugins.cms.src.services.seo_wiring import unregister_seo_pipeline

            unregister_seo_pipeline()
        except Exception as seo_error:
            logging.getLogger(__name__).warning(
                "[cms] Failed to unregister SEO pipeline: %s", seo_error
            )

        # Clear all providers — until a per-provider unregister hook exists,
        # the clear is acceptable because CMS is the only registered provider
        # today. When a second content-owning plugin lands, switch to a
        # per-provider unregister (tracked in [[s10]]: registries→container
        # Singletons, which makes per-plugin scoping automatic).
        clear_access_level_content_providers()
