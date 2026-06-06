"""CmsPostWidget model — assigns a widget to an area of a specific post.

Mirror of ``cms_page_widget`` onto the unified ``cms_post`` (S55). A
post-level assignment overrides the layout-level widget for the same area,
so an admin can change one widget without cloning a whole layout. No unique
constraint: an area may hold multiple ordered widgets, as in the legacy page.
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsPostWidget(BaseModel):
    """Post-level widget assignment.

    Overrides layout-level widget assignments for the same area.
    Allows posts to have unique widgets without creating separate layouts.
    """

    __tablename__ = "cms_post_widget"

    post_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_post.id", ondelete="CASCADE"),
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
            "post_id": str(self.post_id),
            "widget_id": str(self.widget_id),
            "area_name": self.area_name,
            "sort_order": self.sort_order,
            "required_access_level_ids": self.required_access_level_ids or [],
            "created_at": (self.created_at.isoformat() if self.created_at else None),
        }

    def __repr__(self) -> str:
        return f"<CmsPostWidget(post='{self.post_id}', " f"area='{self.area_name}')>"
