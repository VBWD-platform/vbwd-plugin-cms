"""The single canonical-URL derivation rule (S121, DRY).

``cms_post.canonical_url`` is a nullable OVERRIDE, not a requirement. When it is
empty the canonical URL of a page is naturally ``public_base_url + <path>``.
This module is the ONE home for that rule so the meta-builder path (JSON-LD
``url`` + ``<link rel="canonical">``) and the sitemap provider's ``loc`` agree.

Path rule:
  - ``/``        for the home slug (``home_slug``) or an empty slug;
  - ``/<slug>``  otherwise (a nested slug keeps its ``/`` segments).

When ``public_base_url`` is empty the result is a root-relative path (``/docs``,
``/``) — still a valid canonical, and better than emitting ``None``.
"""
from typing import Optional


def _canonical_path(slug: Optional[str], home_slug: Optional[str]) -> str:
    """The root-relative path for a post: ``/`` for home, else ``/<slug>``."""
    normalized_slug = (slug or "").lstrip("/")
    if not normalized_slug:
        return "/"
    if home_slug and normalized_slug == home_slug:
        return "/"
    return f"/{normalized_slug}"


def derive_canonical_url(
    stored_canonical_url: Optional[str],
    slug: Optional[str],
    public_base_url: Optional[str],
    home_slug: Optional[str] = None,
) -> str:
    """Resolve the effective canonical URL for a post.

    A stored ``canonical_url`` wins verbatim (the override). Otherwise derive
    ``<public_base_url><path>``; with no base configured the path alone is
    returned (root-relative). ``home_slug`` (when given) maps the home post to
    the root path ``/``.
    """
    if stored_canonical_url:
        return stored_canonical_url
    base = (public_base_url or "").rstrip("/")
    return f"{base}{_canonical_path(slug, home_slug)}"
