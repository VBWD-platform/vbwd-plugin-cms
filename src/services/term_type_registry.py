"""Term-type registry (S47.0) — the OCP seam for taxonomies.

cms registers the built-ins (``category`` hierarchical, ``tag`` flat);
other plugins register custom term-types with zero cms change. TermService
validates a term's ``term_type`` against this registry (fail-fast on
unknown).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TermType:
    """Declarative description of a registered taxonomy type."""

    key: str
    label: str
    hierarchical: bool


_TERM_TYPES: Dict[str, TermType] = {}


def register_term_type(term_type: TermType) -> None:
    """Register (or replace) a term type by its key."""
    _TERM_TYPES[term_type.key] = term_type


def get_term_type(key: str) -> Optional[TermType]:
    """Return the registered term type for ``key``, or None."""
    return _TERM_TYPES.get(key)


def is_registered(key: str) -> bool:
    """True when a term type with ``key`` is registered."""
    return key in _TERM_TYPES


def list_term_types() -> List[TermType]:
    """Return all registered term types."""
    return list(_TERM_TYPES.values())


def clear_term_types() -> None:
    """Remove all registrations (test isolation / plugin disable)."""
    _TERM_TYPES.clear()
