"""Shared slug utility for import collision handling."""
import re
from typing import Callable


def slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


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
