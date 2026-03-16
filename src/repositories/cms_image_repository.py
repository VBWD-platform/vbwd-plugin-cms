"""CmsImage repository — data access for CMS media gallery."""
from typing import Optional, List, Dict, Any
from plugins.cms.src.models.cms_image import CmsImage


class CmsImageRepository:
    """Repository for CmsImage model database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def find_all(
        self,
        page: int = 1,
        per_page: int = 24,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = self.session.query(CmsImage)
        if search:
            term = f"%{search}%"
            q = q.filter(CmsImage.caption.ilike(term) | CmsImage.slug.ilike(term))

        total = q.count()

        sort_col = getattr(CmsImage, sort_by, CmsImage.created_at)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        items = q.offset((page - 1) * per_page).limit(per_page).all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def find_by_id(self, image_id: str) -> Optional[CmsImage]:
        return self.session.query(CmsImage).filter(CmsImage.id == image_id).first()

    def find_by_slug(self, slug: str) -> Optional[CmsImage]:
        return self.session.query(CmsImage).filter(CmsImage.slug == slug).first()

    def find_by_ids(self, ids: List[str]) -> List[CmsImage]:
        return self.session.query(CmsImage).filter(CmsImage.id.in_(ids)).all()

    def save(self, image: CmsImage) -> CmsImage:
        self.session.add(image)
        self.session.flush()
        self.session.commit()
        return image

    def delete(self, image_id: str) -> bool:
        image = self.find_by_id(image_id)
        if image:
            self.session.delete(image)
            self.session.flush()
            self.session.commit()
            return True
        return False

    def bulk_delete(self, ids: List[str]) -> List[CmsImage]:
        images = self.find_by_ids(ids)
        for img in images:
            self.session.delete(img)
        self.session.flush()
        self.session.commit()
        return images
