"""PostRepository — data access for cms_post (S47.0)."""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import or_, func

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
        language: Optional[str] = None,
        layout_id: Optional[str] = None,
        style_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        newest_first: bool = False,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
    ) -> Dict[str, Any]:
        query = self.session.query(CmsPost)
        if post_type:
            query = query.filter(CmsPost.type == post_type)
        if status:
            query = query.filter(CmsPost.status == status)
        if language:
            query = query.filter(CmsPost.language == language)
        if layout_id:
            query = query.filter(CmsPost.layout_id == layout_id)
        if style_id:
            query = query.filter(CmsPost.style_id == style_id)
        # Time period — date-granular, inclusive, against the shown "updated"
        # column (func.date so a plain YYYY-MM-DD compares cleanly).
        if date_from:
            query = query.filter(func.date(CmsPost.updated_at) >= date_from)
        if date_to:
            query = query.filter(func.date(CmsPost.updated_at) <= date_to)
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
            self._apply_ordering(query, newest_first, sort_by, sort_dir)
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

    # Columns the admin list may sort by (whitelist guards against arbitrary
    # attribute access from a client-supplied sort_by).
    _SORTABLE = {
        "title": CmsPost.title,
        "slug": CmsPost.slug,
        "type": CmsPost.type,
        "status": CmsPost.status,
        "language": CmsPost.language,
        "sort_order": CmsPost.sort_order,
        "created_at": CmsPost.created_at,
        "updated_at": CmsPost.updated_at,
        "published_at": CmsPost.published_at,
    }

    def _apply_ordering(
        self,
        query,
        newest_first: bool,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
    ):
        """Apply the result ordering for a list query.

        An explicit ``sort_by`` (whitelisted column) wins, in ``sort_dir``
        direction. Otherwise: ``newest_first`` (RSS feed) orders by
        ``published_at`` desc; the default (list UI) is ``sort_order`` then
        most-recently-edited.
        """
        column = self._SORTABLE.get((sort_by or "").strip())
        if column is not None:
            ordering = column.desc() if sort_dir == "desc" else column.asc()
            return query.order_by(ordering, CmsPost.id.asc())
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

    def find_by_ids(self, ids: List[str]) -> List[CmsPost]:
        if not ids:
            return []
        return (
            self.session.query(CmsPost)
            .filter(CmsPost.id.in_([str(i) for i in ids]))
            .all()
        )

    def bulk_delete(self, ids: List[str]) -> int:
        posts = self.find_by_ids(ids)
        for post in posts:
            self.session.delete(post)
        self.session.flush()
        self.session.commit()
        return len(posts)
