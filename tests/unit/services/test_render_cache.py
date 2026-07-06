"""S118 Track B — the in-memory TTL render cache (shipped default).

A deterministic clock is injected so expiry is asserted without sleeping.
"""
from plugins.cms.src.services.render_cache import InMemoryTtlRenderCache


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_set_then_get_returns_value_before_expiry():
    clock = _Clock()
    cache = InMemoryTtlRenderCache(clock=clock)
    cache.set("/pricing", "<html>x</html>", 100)
    clock.now = 99.0
    assert cache.get("/pricing") == "<html>x</html>"


def test_entry_expires_after_ttl():
    clock = _Clock()
    cache = InMemoryTtlRenderCache(clock=clock)
    cache.set("/pricing", "<html>x</html>", 100)
    clock.now = 100.0
    assert cache.get("/pricing") is None


def test_missing_key_returns_none():
    assert InMemoryTtlRenderCache().get("/nope") is None


def test_zero_ttl_never_expires():
    clock = _Clock()
    cache = InMemoryTtlRenderCache(clock=clock)
    cache.set("/pricing", "<html>x</html>", 0)
    clock.now = 10_000_000.0
    assert cache.get("/pricing") == "<html>x</html>"


def test_delete_removes_entry():
    cache = InMemoryTtlRenderCache()
    cache.set("/pricing", "<html>x</html>", 100)
    cache.delete("/pricing")
    assert cache.get("/pricing") is None


def test_clear_removes_all_entries():
    cache = InMemoryTtlRenderCache()
    cache.set("/a", "x", 100)
    cache.set("/b", "y", 100)
    cache.clear()
    assert cache.get("/a") is None
    assert cache.get("/b") is None
