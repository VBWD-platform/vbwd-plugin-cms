"""CmsEntityPage — the attachment link between an owner entity and a CmsPost (S128).

An entity page IS a ``cms_post`` (``type=entity_page``, ``routable=False``): it
reuses the whole content stack — content_html/json, ``source_css``, N content
blocks, N widgets, the 10 SEO columns, search vector, i18n. This small link
table is the ONLY new storage: it maps an opaque owner (``owner_type`` +
``owner_id``, one entity page per ``slot``) to its post.

Keeping the link in its own table (not owner columns on ``cms_post``, not a
``page_post_id`` on each entity) preserves SRP and means ZERO schema change in
any adopter plugin. ``slot`` (default ``main``) forward-supports several pages
per entity without a later PK migration; ``owner_id`` is stored as opaque text.
"""
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsEntityPage(BaseModel):
    """Link from an owning entity (owner_type, owner_id, slot) to a CmsPost."""

    __tablename__ = "cms_entity_page"
    __table_args__ = (
        UniqueConstraint(
            "owner_type", "owner_id", "slot", name="uq_cms_entity_page_owner_slot"
        ),
        Index("ix_cms_entity_page_owner", "owner_type", "owner_id"),
    )

    owner_type = db.Column(db.String(64), nullable=False)
    owner_id = db.Column(db.String(255), nullable=False)
    slot = db.Column(
        db.String(64), nullable=False, default="main", server_default="main"
    )
    post_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("cms_post.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "slot": self.slot,
            "post_id": str(self.post_id) if self.post_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CmsEntityPage(owner_type='{self.owner_type}', "
            f"owner_id='{self.owner_id}', slot='{self.slot}')>"
        )
