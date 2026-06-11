"""S52.8 — the cms plugin declares the ``cms:posts:create`` API scope.

Asserted via the CORE scope registry with a fake plugin manager, so the seam
(plugin declares ``api_scopes`` → core collects it without importing cms) is
exercised end-to-end.
"""
from vbwd.services.api_scope_registry import collect_api_scopes
from plugins.cms import CmsPlugin


class _FakeManager:
    def __init__(self, plugins):
        self._plugins = plugins

    def get_enabled_plugins(self):
        return self._plugins


def test_cms_plugin_exposes_create_scope():
    keys = {scope["key"] for scope in CmsPlugin().api_scopes}
    assert "cms:posts:create" in keys


def test_core_registry_surfaces_cms_scope():
    catalog = collect_api_scopes(plugin_manager=_FakeManager([CmsPlugin()]))
    assert catalog["core"] == []
    cms_keys = {scope["key"] for scope in catalog["cms"]}
    assert "cms:posts:create" in cms_keys


def test_cms_create_scope_is_user_grantable():
    scope = next(
        scope for scope in CmsPlugin().api_scopes if scope["key"] == "cms:posts:create"
    )
    assert scope["user_grantable"] is True
