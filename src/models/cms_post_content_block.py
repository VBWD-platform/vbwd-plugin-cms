"""CMS Post Content Block — multiple editable content areas per post.

Mirror of ``cms_page_content_block`` onto the unified ``cms_post`` (S55).
The primary content area stays on ``cms_post.content_html`` (SEO body);
each *additional* ``type:content`` layout area binds to one of these rows.
"""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsPostContentBlock(BaseModel):
    """A named content block within a CMS post.

    Each block corresponds to a 'content' type area in the post's layout.
    Multiple content areas per post are supported (e.g., content-above,
    content-below, sidebar-content).
    """

    __tablename__ = "cms_post_content_block"

    post_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("cms_post.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    area_name = db.Column(db.String(100), nullable=False)
    content_json = db.Column(db.JSON, nullable=True)
    content_html = db.Column(db.Text, nullable=True)
    source_css = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint("post_id", "area_name", name="uq_post_content_block_area"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "post_id": str(self.post_id),
            "area_name": self.area_name,
            "content_json": self.content_json,
            "content_html": self.content_html,
            "source_css": self.source_css,
            "sort_order": self.sort_order,
        }

    def __repr__(self) -> str:
        return f"<CmsPostContentBlock(post={self.post_id}, area='{self.area_name}')>"
