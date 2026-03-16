"""CmsCategory model — hierarchical navigation grouping for CMS pages."""
from __future__ import annotations
from typing import List, TYPE_CHECKING
from sqlalchemy.orm import Mapped, relationship
from src.extensions import db
from src.models.base import BaseModel

if TYPE_CHECKING:
    pass


class CmsCategory(BaseModel):
    """CMS category for grouping pages into navigational sections."""

    __tablename__ = "cms_category"

    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    children: Mapped[List["CmsCategory"]] = relationship(
        "CmsCategory",
        backref=db.backref("parent", remote_side="CmsCategory.id"),
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsCategory(slug='{self.slug}')>"
