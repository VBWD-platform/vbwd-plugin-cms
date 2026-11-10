"""The robots a public cms PATH must carry, for the on-demand render (S154 D7).

``/_seo-render`` captures the SPA at a path; the captured head knows nothing of
the per-type indexable switches. ``SeoPathRobots`` resolves the path the way
the fe catch-all does (page → post → ``category/`` / ``tag/`` term archive) and
answers the robots to force — through the same ``index_robots_override`` rule
the prerender writer applies (DRY) — or ``None`` to serve the render unchanged
(indexable content, or a path cms does not own).
"""
import re
from typing import Optional, Protocol, Sequence

from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, TAG_TERM_TYPE
from plugins.cms.src.services.seo_index_switches import (
    SWITCHED_OFF_ROBOTS,
    SeoIndexSwitches,
    index_robots_override,
    post_type_is_indexable,
    term_type_is_indexable,
)
from plugins.cms.src.services.seo_scope import ScopeView, page_is_search_visible
from plugins.cms.src.services.term_permalink import CATEGORY_URL_PREFIX, TAG_URL_PREFIX

_TERM_TYPE_BY_URL_PREFIX = {
    CATEGORY_URL_PREFIX: CATEGORY_TERM_TYPE,
    TAG_URL_PREFIX: TAG_TERM_TYPE,
}
_TERM_ARCHIVE_PATH_PATTERN = re.compile(
    rf"^({CATEGORY_URL_PREFIX}|{TAG_URL_PREFIX})/.+$"
)


class IPublishedPathLoader(Protocol):
    """The two ``SeoPostLoader`` reads the resolver needs."""

    def find_published_by_path(self, slug: str):
        ...

    def terms_for(self, post) -> list:
        ...


def _slug_of(path: str) -> str:
    """``/a/b/?q`` → ``a/b`` (the ``cms_post.slug`` full-path form)."""
    return (path or "").split("?", 1)[0].split("#", 1)[0].strip().strip("/")


class SeoPathRobots:
    """Resolves the robots override for one public path."""

    def __init__(
        self,
        post_loader: IPublishedPathLoader,
        index_switches: SeoIndexSwitches,
        private_path_prefixes: Sequence[str],
        home_slug: str,
    ) -> None:
        self._post_loader = post_loader
        self._index_switches = index_switches
        self._private_path_prefixes = private_path_prefixes
        self._home_slug = home_slug

    def robots_for(self, path: str) -> Optional[str]:
        slug = _slug_of(path) or self._home_slug
        post = self._post_loader.find_published_by_path(slug)
        if post is not None:
            search_visible = page_is_search_visible(
                ScopeView(post, self._post_loader.terms_for(post)),
                self._private_path_prefixes,
            )
            type_indexable = post_type_is_indexable(self._index_switches, post.type)
            return index_robots_override(search_visible, type_indexable)
        archive_match = _TERM_ARCHIVE_PATH_PATTERN.match(slug)
        if archive_match is None:
            return None
        term_type = _TERM_TYPE_BY_URL_PREFIX[archive_match.group(1)]
        if term_type_is_indexable(self._index_switches, term_type):
            return None
        return SWITCHED_OFF_ROBOTS
