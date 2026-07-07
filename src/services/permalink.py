"""PermalinkRenderer — the pure config→path transform for post permalinks (S122).

The CMS permalink engine is a *write-side transform only*: it computes a post's
full URL path once and stores it into ``cms_post.slug`` (the existing lookup
key), so every read surface (route / sitemap / prerender / canonical) stays
byte-for-byte unchanged.

This module owns the ``%token%`` grammar and the two rendering modes:

* **template** — a free-form string with ``%token%`` placeholders;
* **structured** — guided sugar that is rendered through the *same* template
  engine (``%root%/[%year%/]%category_path%/%slug%``), so the two modes can
  never diverge (DRY).

Rendering is deterministic given its inputs, with one documented exception: when
``published_at`` is ``None`` (a draft/scheduled post with no date yet) the date
tokens fall back to the current UTC time — the same "now" the write path uses
when a post is published without an explicit date.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence

from plugins.cms.src.services._slug import slugify


# Master-switch values (single source; mirrors config.json keys).
PERMALINK_MODE_OFF = "off"
PERMALINK_MODE_STRUCTURED = "structured"
PERMALINK_MODE_TEMPLATE = "template"

# Config defaults (mirror plugins/cms/config.json so a missing config key here
# resolves to the SAME value the operator sees shipped).
DEFAULT_POSTS_ROOT = "blog"
DEFAULT_UNCATEGORIZED_SLUG = "uncategorized"
DEFAULT_TEMPLATE = "%root%/%category%/%slug%"

# The full publish timestamp both ``%timestamp%`` and ``%YYYYMMDDHHmmss%`` use.
_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"

# A ``%token%`` placeholder — letters, digits, underscore (so ``%category_path%``
# and ``%YYYYMMDDHHmmss%`` both match). Matched case-insensitively via ``.lower()``.
_TOKEN_PATTERN = re.compile(r"%([A-Za-z0-9_]+)%")


@dataclass(frozen=True)
class PrimaryCategory:
    """A post's primary category as its ancestor slug chain (root → leaf).

    ``("electronics", "phones", "foldables")`` means ``electronics`` is the
    top-level ancestor and ``foldables`` is the primary term itself. A top-level
    primary is a single-element chain (``("electronics",)``).
    """

    ancestor_slugs: Sequence[str]


class PermalinkRenderer:
    """Renders a post's full URL path from the permalink config (pure)."""

    def render(
        self,
        mode: str,
        config: Optional[dict],
        *,
        slug_base: str,
        primary_term: Optional[PrimaryCategory],
        published_at: Optional[datetime],
        post_id: Optional[str],
    ) -> str:
        """Return the full lookup path (no leading/trailing slash, no ``//``)."""
        config = config or {}
        template = self._template_for(mode, config)
        token_values = self._token_values(
            config, slug_base, primary_term, published_at, post_id
        )
        substituted = _TOKEN_PATTERN.sub(
            lambda match: token_values.get(match.group(1).lower(), ""), template
        )
        # Split on "/" AFTER substitution so a multi-segment token value
        # (``%category_path%`` → ``electronics/phones``) expands into real path
        # segments, then slugify each segment and drop the empties (this is the
        # empty-token collapse — a resolved-to-"" token never leaves a ``//``).
        segments = [slugify(part) for part in substituted.split("/")]
        return "/".join(segment for segment in segments if segment)

    def _template_for(self, mode: str, config: dict) -> str:
        """Resolve the raw template string for the mode.

        Structured mode is sugar: it is assembled into an equivalent template
        and rendered through the same engine, so it can never diverge from the
        template it documents.
        """
        if mode == PERMALINK_MODE_TEMPLATE:
            return config.get("posts_permalink_template") or DEFAULT_TEMPLATE
        parts = ["%root%"]
        if config.get("posts_permalink_include_year"):
            parts.append("%year%")
        parts.append("%category_path%")
        parts.append("%slug%")
        return "/".join(parts)

    def _token_values(
        self,
        config: dict,
        slug_base: str,
        primary_term: Optional[PrimaryCategory],
        published_at: Optional[datetime],
        post_id: Optional[str],
    ) -> Dict[str, str]:
        published = published_at or datetime.now(timezone.utc)
        uncategorized = (
            config.get("posts_permalink_uncategorized_slug")
            or DEFAULT_UNCATEGORIZED_SLUG
        )
        category, subcategory, category_path = self._category_tokens(
            primary_term, uncategorized
        )
        timestamp = published.strftime(_TIMESTAMP_FORMAT)
        return {
            "root": str(config.get("posts_root") or DEFAULT_POSTS_ROOT),
            "slug": slug_base or "",
            "category": category,
            "subcategory": subcategory,
            "category_path": category_path,
            "year": f"{published.year:04d}",
            "month": f"{published.month:02d}",
            "day": f"{published.day:02d}",
            "timestamp": timestamp,
            "yyyymmddhhmmss": timestamp,
            "id": str(post_id) if post_id else "",
        }

    @staticmethod
    def _category_tokens(
        primary_term: Optional[PrimaryCategory], uncategorized: str
    ) -> tuple:
        """Resolve (%category%, %subcategory%, %category_path%).

        With no primary category a category segment must still be present (per
        decision), so ``%category%``/``%category_path%`` fall back to the
        configured uncategorized slug; ``%subcategory%`` stays empty (it has no
        leaf beyond the top level) and collapses.
        """
        ancestors = list(primary_term.ancestor_slugs) if primary_term else []
        ancestors = [slug for slug in ancestors if slug]
        if not ancestors:
            return uncategorized, "", uncategorized
        category = ancestors[0]
        subcategory = ancestors[-1] if len(ancestors) > 1 else ""
        category_path = "/".join(ancestors)
        return category, subcategory, category_path
