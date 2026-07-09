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
    # Per-category "pin" (sticky). A pinned link floats its post to the TOP of
    # that term's archive listing (e.g. ``/category/gadgets``). Scoped to this
    # single post↔term pairing, so a post can be pinned in one category and not
    # another. NOT NULL, defaults False — existing links are unaffected (S-archives).
    pinned = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "post_id": str(self.post_id),
            "term_id": str(self.term_id),
            "pinned": bool(self.pinned),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsPostTerm(post={self.post_id}, term={self.term_id})>"
