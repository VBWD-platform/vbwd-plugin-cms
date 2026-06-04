"""The single search-visibility predicate (S47.1 §3.1).

``page_is_search_visible(post)`` is the ONE source of truth for "may this post
be indexed?". The meta-builder, the prerender writer, and the sitemap provider
all call THIS — no consumer re-implements the rule (DRY).

A post is search-visible iff:
  - its status is ``published``;
  - it is not ``seo_excluded``;
  - none of its terms is ``seo_excluded`` (exclusion is inherited);
  - its ``robots`` does not contain ``noindex``.

The argument is duck-typed: anything exposing ``status``, ``seo_excluded``,
``robots`` and an iterable ``terms`` (each with ``seo_excluded``) works, so the
predicate is testable without the ORM.
"""
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


def page_is_search_visible(post) -> bool:
    """True when ``post`` may appear in search results / the sitemap."""
    if post.status != POST_STATUS_PUBLISHED:
        return False
    if post.seo_excluded:
        return False
    if any(term.seo_excluded for term in (post.terms or [])):
        return False
    if "noindex" in (post.robots or "").lower():
        return False
    return True
