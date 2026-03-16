"""Shared slug utility for import collision handling."""
from typing import Callable


def unique_slug(slug: str, exists_fn: Callable[[str], bool]) -> str:
    """Return slug unchanged if it doesn't exist, else append -2, -3, ... until unique."""
    if not exists_fn(slug):
        return slug
    counter = 2
    while True:
        candidate = f"{slug}-{counter}"
        if not exists_fn(candidate):
            return candidate
        counter += 1
