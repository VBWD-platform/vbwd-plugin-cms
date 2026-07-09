"""Term archive permalink helper — the pure ``(term_type, slug) → path`` map.

CMS term archives live at fixed, permalink-independent URL prefixes:

* categories → ``category/<slug>``
* tags       → ``tag/<slug>``

This is the single source of truth for that convention, so every read surface
(post serialization, the term-resolution endpoint, the fe archive links) derives
the same path and none of them re-hardcodes the prefix. The path is returned
*relative* (no leading slash), matching the ``cms_post.slug`` full-path
convention the frontend already prepends ``/`` to.
"""
from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, TAG_TERM_TYPE


# Fixed archive URL prefixes (permalink-independent). Single source of truth.
CATEGORY_URL_PREFIX = "category"
TAG_URL_PREFIX = "tag"


def term_archive_path(term_type: str, slug: str) -> str:
    """Return a term's archive path: ``category/<slug>`` or ``tag/<slug>``.

    The prefix is fixed per term type (never derived from the permalink config):
    tags map to ``tag/`` and every other (hierarchical) term type maps to
    ``category/``. The result carries no leading/trailing slash.
    """
    prefix = TAG_URL_PREFIX if term_type == TAG_TERM_TYPE else CATEGORY_URL_PREFIX
    return f"{prefix}/{slug.strip('/')}"


def humanize_term_slug(slug: str) -> str:
    """Title-case a slug into a friendly display name (``new-arrivals`` → ``New
    Arrivals``).

    Used for the tag display name: tags live in the core tag index (NOT
    ``cms_term``), so a tag archive has no stored ``name`` and derives one from
    its slug. Nested category slugs keep only the leaf segment.
    """
    leaf = slug.strip("/").split("/")[-1]
    words = [word for word in leaf.split("-") if word]
    return " ".join(word[:1].upper() + word[1:] for word in words)


# Re-exported so callers importing this module have the term-type constants in
# one place alongside the prefix map (DRY; no second import line at call sites).
__all__ = [
    "CATEGORY_URL_PREFIX",
    "TAG_URL_PREFIX",
    "CATEGORY_TERM_TYPE",
    "TAG_TERM_TYPE",
    "term_archive_path",
    "humanize_term_slug",
]
