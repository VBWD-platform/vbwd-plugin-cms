"""CmsCategory repository — data access for CMS categories."""
from typing import Optional, List
from plugins.cms.src.models.cms_category import CmsCategory


class CmsCategoryRepository:
    """Repository for CmsCategory model database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def find_all(self) -> List[CmsCategory]:
        return (
            self.session.query(CmsCategory)
            .order_by(CmsCategory.sort_order, CmsCategory.name)
            .all()
        )

    def find_by_id(self, category_id: str) -> Optional[CmsCategory]:
        return self.session.query(CmsCategory).filter(CmsCategory.id == category_id).first()

    def find_by_slug(self, slug: str) -> Optional[CmsCategory]:
        return self.session.query(CmsCategory).filter(CmsCategory.slug == slug).first()

    def save(self, category: CmsCategory) -> CmsCategory:
        self.session.add(category)
        self.session.flush()
        self.session.commit()
        return category

    def delete(self, category_id: str) -> bool:
        cat = self.find_by_id(category_id)
        if cat:
            self.session.delete(cat)
            self.session.flush()
            self.session.commit()
            return True
        return False
