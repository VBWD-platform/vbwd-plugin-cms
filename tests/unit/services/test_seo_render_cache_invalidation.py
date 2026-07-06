"""S118 Track B increment 4 — event-driven render-cache invalidation.

On a domain change the cms plugin must purge the SAME process-wide render cache
that the ``/_seo-render`` route serves from, so a bot never gets a stale page.

  * ``content.changed`` (a CMS post) → purge THAT post's public path precisely
    (``/`` for the home/empty slug, else ``/<slug>``).
  * another vertical's change (``product.changed`` / booking / dataset / ghrm)
    → the cms plugin never computes that vertical's URL (core-agnostic). If the
    payload carries a canonical path (``path``/``url``/``canonical``) purge just
    that entry; otherwise fall back to a coarse ``invalidate_all`` (never crash).
  * when dynamic render is OFF (or no renderer URL) the subscriber is a cheap
    no-op — it must not purge and must not error.
  * the subscribers register exactly once at plugin enable (idempotent wiring).

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(missing keys ⇒ coarse purge, never a crash); clean code; no overengineering.
Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from typing import Optional

from plugins.cms.src.services import seo_wiring
from plugins.cms.src.services.dynamic_render_service import DynamicRenderService
from plugins.cms.src.services.render_cache import InMemoryTtlRenderCache


class _SpyCache:
    """Dict-backed cache double recording delete / clear calls."""

    def __init__(self) -> None:
        self.store = {}
        self.deleted = []
        self.cleared = 0

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl_seconds):
        self.store[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)

    def clear(self):
        self.cleared += 1
        self.store.clear()


class _CountingRenderClient:
    """Counts render_path calls so a test can prove a re-render happened."""

    def __init__(self, result: Optional[str]) -> None:
        self._result = result
        self.calls = []

    def render_path(self, path: str) -> Optional[str]:
        self.calls.append(path)
        return self._result

    def render_full_page(self, slug, language):  # pragma: no cover - unused
        return self.render_path("/" + (slug or ""))


def _service_over(cache, render_client=None) -> DynamicRenderService:
    return DynamicRenderService(
        render_client=render_client or _CountingRenderClient(None),
        cache=cache,
        minifier=None,
        minify_enabled=lambda: False,
        cache_ttl_seconds=lambda: 900,
    )


def _enable_render(monkeypatch, service) -> None:
    """Force dynamic render ON and route every build to ``service``."""
    monkeypatch.setattr(seo_wiring, "seo_dynamic_render_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_dynamic_render_service", lambda: service)


def test_content_changed_invalidates_that_post_path(monkeypatch):
    cache = _SpyCache()
    cache.store["/pricing"] = "<html>cached</html>"
    _enable_render(monkeypatch, _service_over(cache))

    seo_wiring._on_content_changed_invalidate(
        "content.changed", {"post_id": "p1", "slug": "pricing"}
    )

    assert cache.deleted == ["/pricing"]
    assert "/pricing" not in cache.store


def test_content_changed_home_invalidates_root_path(monkeypatch):
    cache = _SpyCache()
    cache.store["/"] = "<html>home</html>"
    _enable_render(monkeypatch, _service_over(cache))

    seo_wiring._on_content_changed_invalidate(
        "content.changed", {"post_id": "home", "slug": ""}
    )

    assert cache.deleted == ["/"]


def test_product_changed_with_path_payload_invalidates_that_path(monkeypatch):
    cache = _SpyCache()
    cache.store["/shop/widget-42"] = "<html>product</html>"
    _enable_render(monkeypatch, _service_over(cache))

    seo_wiring._on_vertical_changed_invalidate(
        "product.changed", {"product_id": "x", "path": "/shop/widget-42"}
    )

    assert cache.deleted == ["/shop/widget-42"]
    assert cache.cleared == 0  # precise purge, no coarse fallback


def test_domain_event_without_path_payload_invalidates_all(monkeypatch):
    cache = _SpyCache()
    cache.store["/a"] = "x"
    cache.store["/b"] = "y"
    _enable_render(monkeypatch, _service_over(cache))

    # No path/url/canonical key ⇒ the cms plugin cannot compute the URL ⇒ coarse.
    seo_wiring._on_vertical_changed_invalidate(
        "dataset.updated", {"dataset_id": "d1", "slug": "air-quality"}
    )

    assert cache.cleared == 1
    assert cache.store == {}


def test_invalidation_noop_when_dynamic_render_disabled(monkeypatch):
    cache = _SpyCache()
    cache.store["/pricing"] = "<html>cached</html>"
    monkeypatch.setattr(seo_wiring, "seo_dynamic_render_available", lambda: False)
    monkeypatch.setattr(
        seo_wiring, "build_dynamic_render_service", lambda: _service_over(cache)
    )

    seo_wiring._on_content_changed_invalidate(
        "content.changed", {"post_id": "p1", "slug": "pricing"}
    )
    seo_wiring._on_vertical_changed_invalidate("product.changed", {})

    assert cache.deleted == []
    assert cache.cleared == 0
    assert cache.store == {"/pricing": "<html>cached</html>"}


def test_subscriber_registered_once(monkeypatch):
    subscriptions = []

    class _FakeBus:
        def subscribe(self, event_name, callback):
            subscriptions.append((event_name, callback))

        def unsubscribe(self, event_name, callback):  # pragma: no cover - unused
            pass

    monkeypatch.setattr(seo_wiring, "event_bus", _FakeBus())
    # Avoid the sitemap-provider side effects (needs a live session).
    monkeypatch.setattr(seo_wiring, "register_sitemap_provider", lambda provider: None)
    monkeypatch.setattr(
        seo_wiring, "unregister_sitemap_provider", lambda provider: None
    )
    monkeypatch.setattr(seo_wiring, "SeoPostLoader", lambda session: object())
    monkeypatch.setattr(seo_wiring, "CmsSitemapProvider", lambda *a, **k: object())
    monkeypatch.setattr(seo_wiring, "_session", lambda: object())

    seo_wiring.register_seo_pipeline()
    seo_wiring.register_seo_pipeline()

    invalidate_subs = [
        (name, cb)
        for name, cb in subscriptions
        if cb
        in (
            seo_wiring._on_content_changed_invalidate,
            seo_wiring._on_vertical_changed_invalidate,
        )
    ]
    # The EventBus itself dedups, but wiring must pass each callback exactly once
    # per register call, and re-register must reuse the SAME function objects
    # (module-level, not fresh closures) so the bus can dedup them.
    per_register = len(invalidate_subs) // 2
    assert per_register >= 5  # content + product + booking + dataset + ghrm
    first_half = invalidate_subs[:per_register]
    second_half = invalidate_subs[per_register:]
    assert first_half == second_half  # identical (event_name, callback) pairs


def test_purged_path_forces_a_re_render_on_next_render(monkeypatch):
    """End-to-end over the real cache: invalidate ⇒ next render is a miss."""
    cache = InMemoryTtlRenderCache()
    render_client = _CountingRenderClient("<html>page</html>")
    service = _service_over(cache, render_client=render_client)
    _enable_render(monkeypatch, service)

    # Warm the cache for /pricing (one render).
    assert service.render("/pricing") == "<html>page</html>"
    assert render_client.calls == ["/pricing"]

    # A CMS change to that slug purges it via the subscriber...
    seo_wiring._on_content_changed_invalidate(
        "content.changed", {"post_id": "p1", "slug": "pricing"}
    )

    # ...so the next render is a MISS and calls the renderer again.
    assert service.render("/pricing") == "<html>page</html>"
    assert render_client.calls == ["/pricing", "/pricing"]
