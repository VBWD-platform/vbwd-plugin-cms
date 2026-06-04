"""Post-type registry (S47.0) — the OCP seam for content types.

cms registers the built-ins (``page``, ``post``); other plugins register
custom types (``register_post_type(PostType("event", ...))``) with zero cms
change. PostService validates a post's ``type`` against this registry
(fail-fast on unknown) and reads the ``hierarchical`` flag to decide
whether ``parent_id`` is allowed.

A module-level dict is the single source of truth — the same pattern cms
already uses for its access-content / routing registries.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PostType:
    """Declarative description of a registered content type."""

    key: str
    label: str
    routable: bool
    hierarchical: bool = False
    default_template: Optional[str] = None


_POST_TYPES: Dict[str, PostType] = {}


def register_post_type(post_type: PostType) -> None:
    """Register (or replace) a post type by its key."""
    _POST_TYPES[post_type.key] = post_type


def get_post_type(key: str) -> Optional[PostType]:
    """Return the registered post type for ``key``, or None."""
    return _POST_TYPES.get(key)


def is_registered(key: str) -> bool:
    """True when a post type with ``key`` is registered."""
    return key in _POST_TYPES


def list_post_types() -> List[PostType]:
    """Return all registered post types."""
    return list(_POST_TYPES.values())


def clear_post_types() -> None:
    """Remove all registrations (test isolation / plugin disable)."""
    _POST_TYPES.clear()
