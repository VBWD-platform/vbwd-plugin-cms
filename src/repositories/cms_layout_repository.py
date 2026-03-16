"""CmsLayout repository."""
from typing import Optional, List, Dict, Any
from plugins.cms.src.models.cms_layout import CmsLayout


class CmsLayoutRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_slug(self, slug: str) -> Optional[CmsLayout]:
        return self.session.query(CmsLayout).filter(CmsLayout.slug == slug).first()

    def find_by_id(self, layout_id: str) -> Optional[CmsLayout]:
        return self.session.query(CmsLayout).filter(CmsLayout.id == layout_id).first()

    def find_all(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "sort_order",
        sort_dir: str = "asc",
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = self.session.query(CmsLayout)
        if query:
            term = f"%{query}%"
            q = q.filter(CmsLayout.name.ilike(term) | CmsLayout.slug.ilike(term))
        total = q.count()
        sort_col = getattr(CmsLayout, sort_by, CmsLayout.sort_order)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_by_ids(self, ids: List[str]) -> List[CmsLayout]:
        return self.session.query(CmsLayout).filter(CmsLayout.id.in_(ids)).all()

    def save(self, layout: CmsLayout) -> CmsLayout:
        self.session.add(layout)
        self.session.flush()
        self.session.commit()
        return layout

    def delete(self, layout_id: str) -> bool:
        obj = self.find_by_id(layout_id)
        if obj:
            self.session.delete(obj)
            self.session.flush()
            self.session.commit()
            return True
        return False

    def bulk_delete(self, ids: List[str]) -> int:
        deleted = (
            self.session.query(CmsLayout)
            .filter(CmsLayout.id.in_(ids))
            .delete(synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return deleted
