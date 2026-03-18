"""CmsStyle model — plain CSS stylesheet assignable to pages."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsStyle(BaseModel):
    """A named CSS stylesheet that can override theme-switcher styles on a page."""

    __tablename__ = "cms_style"

    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    source_css = db.Column(db.Text, nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "source_css": self.source_css,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsStyle(slug='{self.slug}')>"
