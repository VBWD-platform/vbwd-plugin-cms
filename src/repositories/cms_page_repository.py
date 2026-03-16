"""CmsPage repository — data access for CMS pages."""
from typing import Optional, List, Dict, Any
from plugins.cms.src.models.cms_page import CmsPage


class CmsPageRepository:
    """Repository for CmsPage model database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def find_by_slug(self, slug: str) -> Optional[CmsPage]:
        return self.session.query(CmsPage).filter(CmsPage.slug == slug).first()

    def find_by_id(self, page_id: str) -> Optional[CmsPage]:
        return self.session.query(CmsPage).filter(CmsPage.id == page_id).first()

    def find_all(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "updated_at",
        sort_dir: str = "desc",
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        q = self.session.query(CmsPage)

        if filters:
            if filters.get("category_id"):
                q = q.filter(CmsPage.category_id == filters["category_id"])
            if filters.get("is_published") is not None:
                q = q.filter(CmsPage.is_published == filters["is_published"])
            if filters.get("language"):
                q = q.filter(CmsPage.language == filters["language"])
            if filters.get("search"):
                term = f"%{filters['search']}%"
                q = q.filter(CmsPage.name.ilike(term) | CmsPage.slug.ilike(term))

        total = q.count()

        sort_col = getattr(CmsPage, sort_by, CmsPage.updated_at)
        if sort_dir == "desc":
            q = q.order_by(sort_col.desc())
        else:
            q = q.order_by(sort_col.asc())

        items = q.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_published_by_category(
        self, category_slug: Optional[str], page: int = 1, per_page: int = 20
    ) -> Dict[str, Any]:
        from plugins.cms.src.models.cms_category import CmsCategory

        q = self.session.query(CmsPage).filter(
            CmsPage.is_published is True
        )
        if category_slug:
            q = q.join(CmsCategory, CmsPage.category_id == CmsCategory.id).filter(
                CmsCategory.slug == category_slug
            )
        total = q.count()
        items = (
            q.order_by(CmsPage.sort_order.asc(), CmsPage.updated_at.desc())
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

    def save(self, page: CmsPage) -> CmsPage:
        self.session.add(page)
        self.session.flush()
        self.session.commit()
        return page

    def delete(self, page_id: str) -> bool:
        page = self.find_by_id(page_id)
        if page:
            self.session.delete(page)
            self.session.flush()
            self.session.commit()
            return True
        return False

    def bulk_publish(self, ids: List[str], published: bool) -> int:
        updated = (
            self.session.query(CmsPage)
            .filter(CmsPage.id.in_(ids))
            .update({"is_published": published}, synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return updated

    def bulk_delete(self, ids: List[str]) -> int:
        deleted = (
            self.session.query(CmsPage)
            .filter(CmsPage.id.in_(ids))
            .delete(synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return deleted

    def bulk_set_category(self, ids: List[str], category_id: Optional[str]) -> int:
        updated = (
            self.session.query(CmsPage)
            .filter(CmsPage.id.in_(ids))
            .update({"category_id": category_id}, synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return updated

    def find_by_ids(self, ids: List[str]) -> List[CmsPage]:
        return self.session.query(CmsPage).filter(CmsPage.id.in_(ids)).all()
