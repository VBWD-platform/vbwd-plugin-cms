"""S118 Track B — the on-demand render brain (render-on-miss + cache).

Drives ``DynamicRenderService`` with fakes for the render client and cache:

  * a miss calls the renderer, minifies (when on), and caches the result;
  * a hit returns the cached HTML WITHOUT calling the renderer;
  * a render miss (``None``) returns ``None`` and caches NOTHING (no negative
    cache poisoning) so the route can 502 → SPA shell;
  * minify-off caches the raw HTML even when a minifier tool is present;
  * ``invalidate`` / ``invalidate_all`` purge cache keys (increment 4 seam).

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(a miss never poisons the cache); clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from typing import Optional

from plugins.cms.src.services.dynamic_render_service import DynamicRenderService


class _FakeRenderClient:
    """Records the paths it is asked to render; returns a canned result."""

    def __init__(self, result: Optional[str]):
        self._result = result
        self.calls = []

    def render_path(self, path: str) -> Optional[str]:
        self.calls.append(path)
        return self._result

    def render_full_page(self, slug, language):  # pragma: no cover - unused here
        return self.render_path("/" + (slug or ""))


class _FakeCache:
    """A trivial dict-backed cache double (no TTL logic under test here)."""

    def __init__(self):
        self.store = {}
        self.set_calls = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl_seconds):
        self.store[key] = value
        self.set_calls.append((key, value, ttl_seconds))

    def delete(self, key):
        self.store.pop(key, None)

    def clear(self):
        self.store.clear()


class _MarkerMinifier:
    """Fake minifier: prefixes a marker so a test can prove it ran."""

    def minify(self, html: str) -> str:
        return "MIN:" + html


def _service(client, cache, minifier=None, minify_on=True, ttl=1800):
    return DynamicRenderService(
        render_client=client,
        cache=cache,
        minifier=minifier,
        minify_enabled=lambda: minify_on,
        cache_ttl_seconds=lambda: ttl,
    )


def test_miss_calls_renderer_minifies_and_caches():
    client = _FakeRenderClient("<html>page</html>")
    cache = _FakeCache()
    service = _service(
        client, cache, minifier=_MarkerMinifier(), minify_on=True, ttl=900
    )

    result = service.render("/pricing")

    assert result == "MIN:<html>page</html>"
    assert client.calls == ["/pricing"]
    assert cache.store["/pricing"] == "MIN:<html>page</html>"
    assert cache.set_calls == [("/pricing", "MIN:<html>page</html>", 900)]


def test_hit_returns_cache_without_calling_renderer():
    client = _FakeRenderClient("<html>fresh</html>")
    cache = _FakeCache()
    cache.store["/pricing"] = "<html>cached</html>"
    service = _service(client, cache, minifier=_MarkerMinifier())

    result = service.render("/pricing")

    assert result == "<html>cached</html>"
    assert client.calls == []  # renderer never touched on a hit


def test_renderer_none_returns_none_and_does_not_cache():
    client = _FakeRenderClient(None)
    cache = _FakeCache()
    service = _service(client, cache, minifier=_MarkerMinifier())

    assert service.render("/pricing") is None
    assert cache.store == {}  # a miss is never cached (no poisoning)


def test_minify_off_caches_raw_html():
    client = _FakeRenderClient("<html>raw</html>")
    cache = _FakeCache()
    service = _service(client, cache, minifier=_MarkerMinifier(), minify_on=False)

    result = service.render("/pricing")

    assert result == "<html>raw</html>"  # minifier present but flag off ⇒ untouched
    assert cache.store["/pricing"] == "<html>raw</html>"


def test_no_minifier_tool_caches_raw_html_even_when_flag_on():
    client = _FakeRenderClient("<html>raw</html>")
    cache = _FakeCache()
    service = _service(client, cache, minifier=None, minify_on=True)

    assert service.render("/pricing") == "<html>raw</html>"


def test_invalidate_purges_key():
    client = _FakeRenderClient("<html>page</html>")
    cache = _FakeCache()
    cache.store["/pricing"] = "<html>cached</html>"
    service = _service(client, cache)

    service.invalidate("/pricing")

    assert "/pricing" not in cache.store


def test_invalidate_all_clears():
    cache = _FakeCache()
    cache.store["/a"] = "x"
    cache.store["/b"] = "y"
    service = _service(_FakeRenderClient(None), cache)

    service.invalidate_all()

    assert cache.store == {}


def test_path_is_normalised_for_the_cache_key():
    """A trailing slash and a missing leading slash collapse to one key."""
    client = _FakeRenderClient("<html>page</html>")
    cache = _FakeCache()
    service = _service(client, cache)

    service.render("/pricing/")
    # A subsequent hit on the canonical form is served from cache (no re-render).
    assert service.render("/pricing") == "<html>page</html>"
    assert client.calls == ["/pricing/"]  # only the first triggered a render
