"""DB-backed loader feeding the prerender writer + sitemap provider (S47.1).

Both SEO consumers are pure (no ORM). This loader is the single glue that
reads ``cms_post`` rows, their attached terms (for the exclusion-inheritance
predicate), and their translation siblings (for hreflang) from a SQLAlchemy
session. Keeping the loader separate keeps the writer/provider unit-testable
with simple doubles.
"""
from typing import List, Optional, Tuple

from plugins.cms.src.models.cms_post import CmsPost, POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.models.cms_post_term import CmsPostTerm


class _Sibling:
    """A translation sibling (language + canonical + slug) for hreflang.

    ``slug`` lets the sitemap provider build a fallback href when the sibling
    has no stored ``canonical_url`` (the same fallback the canonical post uses).
    """

    def __init__(
        self,
        language: str,
        canonical_url: Optional[str],
        slug: Optional[str] = None,
    ) -> None:
        self.language = language
        self.canonical_url = canonical_url
        self.slug = slug


class SeoPostLoader:
    """Reads posts + their terms + translation siblings for the SEO pipeline."""

    def __init__(self, session) -> None:
        self._session = session

    # ── prerender writer interface ───────────────────────────────────────

    def load(self, post_id: str) -> Optional[Tuple[CmsPost, list, list]]:
        post = self._session.query(CmsPost).filter(CmsPost.id == post_id).first()
        if post is None:
            return None
        return post, self.terms_for(post), self.siblings_for(post)

    # ── sitemap provider interface ───────────────────────────────────────

    def iter_candidate_posts(self) -> List[CmsPost]:
        """Only ``published`` posts can ever be search-visible (D9)."""
        return (
            self._session.query(CmsPost)
            .filter(CmsPost.status == POST_STATUS_PUBLISHED)
            .all()
        )

    def terms_for(self, post: CmsPost) -> List[CmsTerm]:
        return (
            self._session.query(CmsTerm)
            .join(CmsPostTerm, CmsPostTerm.term_id == CmsTerm.id)
            .filter(CmsPostTerm.post_id == post.id)
            .all()
        )

    def siblings_for(self, post: CmsPost) -> List[_Sibling]:
        if not post.translation_group_id:
            return []
        rows = (
            self._session.query(CmsPost)
            .filter(
                CmsPost.translation_group_id == post.translation_group_id,
                CmsPost.id != post.id,
            )
            .all()
        )
        return [_Sibling(row.language, row.canonical_url, row.slug) for row in rows]
