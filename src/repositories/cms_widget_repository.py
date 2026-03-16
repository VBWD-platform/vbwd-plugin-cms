"""CmsWidget repository."""
from typing import Optional, List, Dict, Any
from plugins.cms.src.models.cms_widget import CmsWidget


class CmsWidgetRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_slug(self, slug: str) -> Optional[CmsWidget]:
        return self.session.query(CmsWidget).filter(CmsWidget.slug == slug).first()

    def find_by_id(self, widget_id: str) -> Optional[CmsWidget]:
        return self.session.query(CmsWidget).filter(CmsWidget.id == widget_id).first()

    def find_all(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "sort_order",
        sort_dir: str = "asc",
        query: Optional[str] = None,
        widget_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = self.session.query(CmsWidget)
        if query:
            term = f"%{query}%"
            q = q.filter(CmsWidget.name.ilike(term) | CmsWidget.slug.ilike(term))
        if widget_type:
            q = q.filter(CmsWidget.widget_type == widget_type)
        total = q.count()
        sort_col = getattr(CmsWidget, sort_by, CmsWidget.sort_order)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_by_ids(self, ids: List[str]) -> List[CmsWidget]:
        return self.session.query(CmsWidget).filter(CmsWidget.id.in_(ids)).all()

    def save(self, widget: CmsWidget) -> CmsWidget:
        self.session.add(widget)
        self.session.flush()
        self.session.commit()
        return widget

    def delete(self, widget_id: str) -> bool:
        obj = self.find_by_id(widget_id)
        if obj:
            self.session.delete(obj)
            self.session.flush()
            self.session.commit()
            return True
        return False

    def bulk_delete(self, ids: List[str]) -> int:
        deleted = (
            self.session.query(CmsWidget)
            .filter(CmsWidget.id.in_(ids))
            .delete(synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return deleted
