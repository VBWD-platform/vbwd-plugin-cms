"""PostRepository — data access for cms_post (S47.0)."""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import or_

from plugins.cms.src.models.cms_post import (
    CmsPost,
    POST_STATUS_SCHEDULED,
    POST_STATUS_PUBLISHED,
)
from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.models.cms_post_term import CmsPostTerm


class PostRepository:
    """Repository for CmsPost database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def find_by_id(self, post_id: str) -> Optional[CmsPost]:
        return self.session.query(CmsPost).filter(CmsPost.id == post_id).first()

    def find_by_type_and_slug(self, post_type: str, slug: str) -> Optional[CmsPost]:
        return (
            self.session.query(CmsPost)
            .filter(CmsPost.type == post_type, CmsPost.slug == slug)
            .first()
        )

    def find_paginated(
        self,
        post_type: Optional[str] = None,
        status: Optional[str] = None,
        term_id: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
    ) -> Dict[str, Any]:
        query = self.session.query(CmsPost)
        if post_type:
            query = query.filter(CmsPost.type == post_type)
        if status:
            query = query.filter(CmsPost.status == status)
        if term_id:
            query = query.join(CmsPostTerm, CmsPostTerm.post_id == CmsPost.id).filter(
                CmsPostTerm.term_id == term_id
            )
        if search:
            # Admin list quick-search: case-insensitive substring over title +
            # slug (the columns shown in the list). Not the public FTS path.
            like = f"%{search.strip()}%"
            query = query.filter(
                or_(CmsPost.title.ilike(like), CmsPost.slug.ilike(like))
            )

        total = query.count()
        items = (
            self._apply_ordering(query, newest_first)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_by_term_slug(
        self,
        term_type: str,
        term_slug: str,
        post_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
    ) -> Dict[str, Any]:
        query = (
            self.session.query(CmsPost)
            .join(CmsPostTerm, CmsPostTerm.post_id == CmsPost.id)
            .join(CmsTerm, CmsTerm.id == CmsPostTerm.term_id)
            .filter(CmsTerm.term_type == term_type, CmsTerm.slug == term_slug)
        )
        if post_type:
            query = query.filter(CmsPost.type == post_type)
        if status:
            query = query.filter(CmsPost.status == status)

        total = query.count()
        items = (
            self._apply_ordering(query, newest_first)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def _apply_ordering(self, query, newest_first: bool):
        """Apply the result ordering for a list query.

        Default (list/archive UI) is ``sort_order`` then most-recently-edited.
        ``newest_first`` (used by the RSS feed) orders by ``published_at``
        descending — newest published first — with ``created_at`` as a stable
        tiebreak for rows sharing (or missing) a publish timestamp.
        """
        if newest_first:
            return query.order_by(
                CmsPost.published_at.desc().nullslast(),
                CmsPost.created_at.desc(),
            )
        return query.order_by(CmsPost.sort_order.asc(), CmsPost.updated_at.desc())

    def find_scheduled_due(self, now: Optional[datetime] = None) -> List[CmsPost]:
        """Scheduled posts whose published_at has passed."""
        moment = now or datetime.now(timezone.utc)
        return (
            self.session.query(CmsPost)
            .filter(
                CmsPost.status == POST_STATUS_SCHEDULED,
                CmsPost.published_at.isnot(None),
                CmsPost.published_at <= moment,
            )
            .all()
        )

    def find_all_published(self) -> List[CmsPost]:
        """Every published post of any type — used for SEO prerender regen."""
        return (
            self.session.query(CmsPost)
            .filter(CmsPost.status == POST_STATUS_PUBLISHED)
            .all()
        )

    def save(self, post: CmsPost) -> CmsPost:
        self.session.add(post)
        self.session.flush()
        self.session.commit()
        return post

    def delete(self, post_id: str) -> bool:
        post = self.find_by_id(post_id)
        if post:
            self.session.delete(post)
            self.session.flush()
            self.session.commit()
            return True
        return False
