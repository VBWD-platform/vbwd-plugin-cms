"""CmsWidget model — reusable content block assigned to layout areas."""
from src.extensions import db
from src.models.base import BaseModel

WIDGET_TYPES = frozenset({"html", "menu", "slideshow", "vue-component"})


class CmsWidget(BaseModel):
    """A reusable content block of a given type (html, menu, slideshow)."""

    __tablename__ = "cms_widget"

    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    widget_type = db.Column(db.String(32), nullable=False)
    content_json = db.Column(db.JSON, nullable=True)
    source_css = db.Column(db.Text, nullable=True)
    config = db.Column(db.JSON, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "widget_type": self.widget_type,
            "content_json": self.content_json,
            "source_css": self.source_css,
            "config": self.config,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsWidget(slug='{self.slug}', type='{self.widget_type}')>"
