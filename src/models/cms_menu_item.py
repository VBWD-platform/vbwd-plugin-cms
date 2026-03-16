"""CmsMenuItem model — node in a multilevel navigation menu widget."""
from src.extensions import db
from src.models.base import BaseModel


class CmsMenuItem(BaseModel):
    """A single item in a cms_widget of type=menu. Self-referential for nesting."""

    __tablename__ = "cms_menu_item"

    widget_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_widget.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_menu_item.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    label = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(512), nullable=True)
    page_slug = db.Column(db.String(512), nullable=True)
    target = db.Column(db.String(16), nullable=False, default="_self")
    icon = db.Column(db.String(64), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "widget_id": str(self.widget_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "label": self.label,
            "url": self.url,
            "page_slug": self.page_slug,
            "target": self.target,
            "icon": self.icon,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsMenuItem(label='{self.label}', widget_id='{self.widget_id}')>"
