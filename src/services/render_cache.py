"""S118 Track B — the render-cache abstraction for on-demand full renders.

``DynamicRenderService`` caches a rendered page keyed by its normalised public
path so a bot hitting the same route again is served from cache without a
(slow, paid) headless render. The cache is a narrow port (``get``/``set``/
``delete``/``clear``) so the service depends only on the methods it uses (ISP)
and a test can inject a trivial fake.

The shipped default is an in-memory TTL cache. It is per-process, so in a
multi-worker gunicorn deployment each worker keeps its own copy — acceptable
for a short-TTL bot cache (a miss on another worker just triggers one render),
but see the TODO for the Redis upgrade path.
"""
import time
from typing import Callable, Dict, Optional, Protocol, Tuple


class RenderCache(Protocol):
    """Narrow cache port used by ``DynamicRenderService``."""

    def get(self, key: str) -> Optional[str]:
        ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def clear(self) -> None:
        ...


class InMemoryTtlRenderCache(RenderCache):
    """A tiny per-process TTL cache (the shipped default).

    # TODO(increment): swap for a Redis-backed impl so the cache is shared
    # across gunicorn workers (this in-memory default is per-worker).

    ``ttl_seconds <= 0`` stores the entry without expiry. A ``clock`` is
    injectable so tests can advance time deterministically instead of sleeping.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: Dict[str, Tuple[str, Optional[float]]] = {}
        self._clock = clock

    def get(self, key: str) -> Optional[str]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._clock() >= expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = (
            self._clock() + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        )
        self._entries[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
