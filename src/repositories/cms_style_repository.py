"""CmsStyle repository."""
from typing import Optional, List, Dict, Any
from plugins.cms.src.models.cms_style import CmsStyle


class CmsStyleRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_slug(self, slug: str) -> Optional[CmsStyle]:
        return self.session.query(CmsStyle).filter(CmsStyle.slug == slug).first()

    def find_by_id(self, style_id: str) -> Optional[CmsStyle]:
        return self.session.query(CmsStyle).filter(CmsStyle.id == style_id).first()

    def find_all(
        self,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "sort_order",
        sort_dir: str = "asc",
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = self.session.query(CmsStyle)
        if query:
            term = f"%{query}%"
            q = q.filter(CmsStyle.name.ilike(term) | CmsStyle.slug.ilike(term))
        total = q.count()
        sort_col = getattr(CmsStyle, sort_by, CmsStyle.sort_order)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_by_ids(self, ids: List[str]) -> List[CmsStyle]:
        return self.session.query(CmsStyle).filter(CmsStyle.id.in_(ids)).all()

    def save(self, style: CmsStyle) -> CmsStyle:
        self.session.add(style)
        self.session.flush()
        self.session.commit()
        return style

    def delete(self, style_id: str) -> bool:
        obj = self.find_by_id(style_id)
        if obj:
            self.session.delete(obj)
            self.session.flush()
            self.session.commit()
            return True
        return False

    def bulk_delete(self, ids: List[str]) -> int:
        deleted = (
            self.session.query(CmsStyle)
            .filter(CmsStyle.id.in_(ids))
            .delete(synchronize_session="fetch")
        )
        self.session.flush()
        self.session.commit()
        return deleted
