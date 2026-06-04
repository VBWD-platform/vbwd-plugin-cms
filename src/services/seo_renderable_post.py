"""Adapter: a ``cms_post`` (+ its terms + translation siblings) presented as a
core ``SeoRenderable`` for the meta-builder (S47.1).

The meta-builder consumes the agnostic ``SeoRenderable`` protocol, never a
``cms_post`` directly. This thin wrapper exposes the post's SEO columns, its
``schema_type`` (default ``WebPage``), and its hreflang siblings, and carries an
``effective_robots`` override so an excluded-but-published post renders with
``noindex,nofollow`` without mutating the stored row.
"""
from dataclasses import dataclass
from typing import List, Optional

WEBPAGE_SCHEMA_TYPE = "WebPage"
NOINDEX_ROBOTS = "noindex,nofollow"


@dataclass
class RenderableSibling:
    """A translation sibling for hreflang generation."""

    language: str
    canonical_url: Optional[str]


class RenderablePost:
    """Wraps a cms_post so the meta-builder sees a ``SeoRenderable``."""

    def __init__(
        self,
        post,
        siblings: Optional[List[RenderableSibling]] = None,
        robots_override: Optional[str] = None,
    ) -> None:
        self._post = post
        self.slug = post.slug
        self.language = getattr(post, "language", "en")
        self.title = post.title
        self.meta_title = post.meta_title
        self.meta_description = post.meta_description
        self.meta_keywords = post.meta_keywords
        self.og_title = post.og_title
        self.og_description = post.og_description
        self.og_image_url = post.og_image_url
        self.canonical_url = post.canonical_url
        self.schema_json = post.schema_json
        self.schema_type = WEBPAGE_SCHEMA_TYPE
        self.robots = robots_override or post.robots
        self.translation_siblings = siblings or []

    def is_search_visible(self) -> bool:
        return "noindex" not in (self.robots or "").lower()
