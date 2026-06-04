"""TermRepository — data access for cms_term (S47.0)."""
from typing import Optional, List

from plugins.cms.src.models.cms_term import CmsTerm


class TermRepository:
    """Repository for CmsTerm database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def find_by_id(self, term_id: str) -> Optional[CmsTerm]:
        return self.session.query(CmsTerm).filter(CmsTerm.id == term_id).first()

    def find_all(self) -> List[CmsTerm]:
        return (
            self.session.query(CmsTerm)
            .order_by(
                CmsTerm.term_type.asc(),
                CmsTerm.sort_order.asc(),
                CmsTerm.name.asc(),
            )
            .all()
        )

    def find_by_type(self, term_type: str) -> List[CmsTerm]:
        return (
            self.session.query(CmsTerm)
            .filter(CmsTerm.term_type == term_type)
            .order_by(CmsTerm.sort_order.asc(), CmsTerm.name.asc())
            .all()
        )

    def find_by_type_and_slug(self, term_type: str, slug: str) -> Optional[CmsTerm]:
        return (
            self.session.query(CmsTerm)
            .filter(CmsTerm.term_type == term_type, CmsTerm.slug == slug)
            .first()
        )

    def find_children(self, parent_id: str) -> List[CmsTerm]:
        return (
            self.session.query(CmsTerm)
            .filter(CmsTerm.parent_id == parent_id)
            .order_by(CmsTerm.sort_order.asc(), CmsTerm.name.asc())
            .all()
        )

    def save(self, term: CmsTerm) -> CmsTerm:
        self.session.add(term)
        self.session.flush()
        self.session.commit()
        return term

    def delete(self, term_id: str) -> bool:
        term = self.find_by_id(term_id)
        if term:
            self.session.delete(term)
            self.session.flush()
            self.session.commit()
            return True
        return False
