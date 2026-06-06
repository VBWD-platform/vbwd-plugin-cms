"""CmsTerm model — unified taxonomy entity (S47.0).

A single ``term`` row with a ``term_type`` discriminator (``category``/
``tag``/plugin-defined). ``cms_category`` migrates into this table as
``term_type=category`` in a later run. Hierarchy (``parent_id``) is used
by hierarchical term-types (categories); flat ones (tags) leave it null.
"""
from sqlalchemy import UniqueConstraint
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# The ``term_type`` discriminator value for category terms (the unified taxonomy
# replacement for the legacy cms_category table). Single source of truth.
CATEGORY_TERM_TYPE = "category"


class CmsTerm(BaseModel):
    """A single taxonomy term (category, tag, or custom type)."""

    __tablename__ = "cms_term"
    __table_args__ = (
        UniqueConstraint("term_type", "slug", name="uq_cms_term_type_slug"),
    )

    term_type = db.Column(db.String(64), nullable=False, index=True)
    slug = db.Column(db.String(128), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    parent_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_term.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description = db.Column(db.Text, nullable=True)
    seo_excluded = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "term_type": self.term_type,
            "slug": self.slug,
            "name": self.name,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "description": self.description,
            "seo_excluded": self.seo_excluded,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsTerm(term_type='{self.term_type}', slug='{self.slug}')>"
