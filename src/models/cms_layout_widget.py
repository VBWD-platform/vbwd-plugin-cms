"""CmsLayoutWidget model — assigns a widget to an area slot in a layout."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsLayoutWidget(BaseModel):
    """Join table: a widget assigned to a named area of a layout."""

    __tablename__ = "cms_layout_widget"

    layout_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_layout.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    widget_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_widget.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    area_name = db.Column(db.String(64), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    required_access_level_ids = db.Column(db.JSON, nullable=False, default=list)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "layout_id": str(self.layout_id),
            "widget_id": str(self.widget_id),
            "area_name": self.area_name,
            "sort_order": self.sort_order,
            "required_access_level_ids": self.required_access_level_ids or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsLayoutWidget(layout='{self.layout_id}', area='{self.area_name}')>"
