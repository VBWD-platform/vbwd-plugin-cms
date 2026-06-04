"""CmsPostTerm model — post↔term junction (S47.0)."""
from sqlalchemy import UniqueConstraint
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsPostTerm(BaseModel):
    """Many-to-many link between a post and a taxonomy term.

    Both FKs cascade on delete: deleting a post (or a term) removes the
    junction rows but leaves the other side intact.
    """

    __tablename__ = "cms_post_term"
    __table_args__ = (UniqueConstraint("post_id", "term_id", name="uq_cms_post_term"),)

    post_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_post.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_term.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "post_id": str(self.post_id),
            "term_id": str(self.term_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsPostTerm(post={self.post_id}, term={self.term_id})>"
