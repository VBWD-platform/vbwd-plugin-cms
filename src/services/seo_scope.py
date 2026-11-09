"""The single search-visibility predicate (S47.1 §3.1).

``page_is_search_visible(post)`` is the ONE source of truth for "may this post
be indexed?". The meta-builder, the prerender writer, and the sitemap provider
all call THIS — no consumer re-implements the rule (DRY).

A post is search-visible iff:
  - its status is ``published``;
  - it is not ``seo_excluded``;
  - none of its terms is ``seo_excluded`` (exclusion is inherited);
  - its ``robots`` does not contain ``noindex``;
  - its public path is not under a private path prefix (``/dashboard``,
    ``/tuktuk``, ``/pay``, ``/software`` by default — config
    ``seo_private_path_prefixes``).

The argument is duck-typed: anything exposing ``status``, ``seo_excluded``,
``robots``, ``slug`` and an iterable ``terms`` (each with ``seo_excluded``)
works, so the predicate is testable without the ORM.
"""
from typing import Sequence, Tuple

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED

PRIVATE_PATH_PREFIXES_CONFIG_KEY = "seo_private_path_prefixes"
# Private app areas that must never be indexed, whatever a post's own robots
# value says. Overridable via ``seo_private_path_prefixes`` in the cms config.
DEFAULT_PRIVATE_PATH_PREFIXES: Tuple[str, ...] = (
    "/dashboard",
    "/tuktuk",
    "/pay",
    "/software",
)


def _normalise_path(path: str) -> str:
    """``/a/b`` form: query/fragment dropped, one leading slash, no trailing."""
    bare_path = (path or "").split("?", 1)[0].split("#", 1)[0].strip()
    return "/" + bare_path.strip("/")


def resolve_private_path_prefixes(config: dict) -> Tuple[str, ...]:
    """The effective private prefixes: the saved value, else the defaults.

    Accepts a list or a comma-separated string (the generic admin config form
    saves text); blank entries are dropped so ``/`` never privatises the site.
    """
    configured = config.get(
        PRIVATE_PATH_PREFIXES_CONFIG_KEY, DEFAULT_PRIVATE_PATH_PREFIXES
    )
    if isinstance(configured, str):
        configured = configured.split(",")
    normalised = (_normalise_path(str(prefix)) for prefix in configured or ())
    return tuple(prefix for prefix in normalised if prefix != "/")


def path_is_private(path: str, private_path_prefixes: Sequence[str]) -> bool:
    """True when ``path`` is a private prefix or lies beneath one (segment-aware:
    ``/pay`` matches ``/pay`` and ``/pay/x``, never ``/payments``)."""
    candidate = _normalise_path(path).casefold()
    for prefix in private_path_prefixes:
        normalised_prefix = _normalise_path(prefix).casefold()
        if normalised_prefix == "/":
            continue
        if candidate == normalised_prefix or candidate.startswith(
            normalised_prefix + "/"
        ):
            return True
    return False


def page_is_search_visible(post, private_path_prefixes: Sequence[str] = ()) -> bool:
    """True when ``post`` may appear in search results / the sitemap."""
    if post.status != POST_STATUS_PUBLISHED:
        return False
    if post.seo_excluded:
        return False
    if any(term.seo_excluded for term in (post.terms or [])):
        return False
    if "noindex" in (post.robots or "").lower():
        return False
    if path_is_private(getattr(post, "slug", "") or "", private_path_prefixes):
        return False
    return True


class ScopeView:
    """Adapts (post, terms) into the duck-typed shape the predicate expects."""

    def __init__(self, post, terms) -> None:
        self.status = post.status
        self.seo_excluded = post.seo_excluded
        self.robots = post.robots
        self.slug = post.slug
        self.terms = terms or []
