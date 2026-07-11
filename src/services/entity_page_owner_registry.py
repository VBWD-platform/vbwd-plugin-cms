"""Content-owner-type registry (S128) — the OCP seam for entity pages.

A sibling of ``post_type_registry``: where that registry names the *content*
dimension (``page`` / ``post`` / plugin types), this one names the *owner*
dimension — the opaque entity an entity page is attached to (``dataset`` /
``shop_product`` / ``booking_resource`` / a merchant's own key). CMS never
hardcodes a vertical: an adopter plugin registers its owner type (with an
``authorize`` callback) in ``on_enable`` and the generic entity-page routes look
it up, so a new vertical is a *registration*, never a cms edit.

A module-level dict is the single source of truth — the exact pattern cms
already uses for its post-type / term-type / routing registries (DRY).
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class ContentOwnerType:
    """Declarative description of a registered entity-page owner type.

    ``authorize(user, owner_id)`` answers "may this user edit this owner's
    page?" — the adopter owns the permission logic (e.g. ``dataset.manage`` on
    that dataset), so no vertical permission ever leaks into CMS.
    """

    key: str
    label: str
    authorize: Callable[[object, str], bool]


_CONTENT_OWNER_TYPES: Dict[str, ContentOwnerType] = {}


def register_content_owner_type(owner_type: ContentOwnerType) -> None:
    """Register (or replace) a content-owner type by its key."""
    _CONTENT_OWNER_TYPES[owner_type.key] = owner_type


def get_content_owner_type(key: str) -> Optional[ContentOwnerType]:
    """Return the registered owner type for ``key``, or None."""
    return _CONTENT_OWNER_TYPES.get(key)


def is_registered(key: str) -> bool:
    """True when an owner type with ``key`` is registered."""
    return key in _CONTENT_OWNER_TYPES


def list_content_owner_types() -> List[ContentOwnerType]:
    """Return all registered owner types."""
    return list(_CONTENT_OWNER_TYPES.values())


def clear_content_owner_types() -> None:
    """Remove all registrations (test isolation / plugin disable)."""
    _CONTENT_OWNER_TYPES.clear()
