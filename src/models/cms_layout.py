"""CmsLayout model — named page structure template with ordered area slots."""
from src.extensions import db
from src.models.base import BaseModel

AREA_TYPES = frozenset(
    {
        "header",
        "footer",
        "hero",
        "slideshow",
        "content",
        "three-column",
        "two-column",
        "cta-bar",
        "vue",
    }
)


class CmsLayout(BaseModel):
    """A named layout template composed of ordered area definitions."""

    __tablename__ = "cms_layout"

    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    areas = db.Column(db.JSON, nullable=False, default=list)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "areas": self.areas,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsLayout(slug='{self.slug}')>"
