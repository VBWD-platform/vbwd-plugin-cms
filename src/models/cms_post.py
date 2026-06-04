"""CmsPost model — unified content entity (S47.0).

A single ``post`` row with a ``type`` discriminator (``page``/``post``/
plugin-defined). ``cms_page`` migrates into this table as ``type=page``
in a later run. Hierarchy (``parent_id`` → nested URLs) is permitted only
for post-types flagged ``hierarchical`` — enforced in PostService, not at
the DB level, so a single self-FK serves both flat and nested types.
"""
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from vbwd.extensions import db
from vbwd.models.base import BaseModel


# Full-text search weighting (S47.4). A weighted tsvector over title (A),
# excerpt (B), and the HTML-stripped body (C), so a title hit outranks a body
# hit. HTML tags are stripped in pure SQL (regexp_replace) so the generated
# column stays correct without any trigger/Python code. ``english`` is the
# default config; per-language config is a future refinement (D-scope).
# This single expression is the source of truth for both the model's generated
# column (via ``create_all``) and the in-plugin Alembic migration (DRY).
SEARCH_VECTOR_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(excerpt, '')), 'B') || "
    "setweight("
    "to_tsvector('english', "
    "regexp_replace(coalesce(content_html, ''), '<[^>]+>', ' ', 'g')), 'C')"
)
SEARCH_VECTOR_INDEX = "ix_cms_post_search_vector"


# Status lifecycle (D9). Only ``published`` is publicly listed; ``private``
# requires an authorized session; ``trash`` is soft-delete.
POST_STATUS_DRAFT = "draft"
POST_STATUS_PENDING = "pending"
POST_STATUS_SCHEDULED = "scheduled"
POST_STATUS_PUBLISHED = "published"
POST_STATUS_PRIVATE = "private"
POST_STATUS_TRASH = "trash"

POST_STATUSES = (
    POST_STATUS_DRAFT,
    POST_STATUS_PENDING,
    POST_STATUS_SCHEDULED,
    POST_STATUS_PUBLISHED,
    POST_STATUS_PRIVATE,
    POST_STATUS_TRASH,
)


class CmsPost(BaseModel):
    """A single unified content item (page, post, or custom type)."""

    __tablename__ = "cms_post"
    __table_args__ = (
        UniqueConstraint("type", "slug", name="uq_cms_post_type_slug"),
        Index(
            SEARCH_VECTOR_INDEX,
            "search_vector",
            postgresql_using="gin",
        ),
    )

    type = db.Column(db.String(64), nullable=False, index=True)
    slug = db.Column(db.String(512), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    excerpt = db.Column(db.Text, nullable=True)
    featured_image_url = db.Column(db.String(512), nullable=True)
    content_json = db.Column(db.JSON, nullable=False, default=dict)
    content_html = db.Column(db.Text, nullable=True)
    type_data = db.Column(db.JSON, nullable=True)

    author_id = db.Column(
        db.UUID,
        db.ForeignKey("vbwd_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_post.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = db.Column(
        db.String(16),
        nullable=False,
        default=POST_STATUS_DRAFT,
        index=True,
    )
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    language = db.Column(db.String(8), nullable=False, default="en")
    translation_group_id = db.Column(db.UUID, nullable=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    # SEO columns (mirrored from cms_page).
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    meta_keywords = db.Column(db.Text, nullable=True)
    og_title = db.Column(db.String(255), nullable=True)
    og_description = db.Column(db.Text, nullable=True)
    og_image_url = db.Column(db.String(512), nullable=True)
    canonical_url = db.Column(db.String(512), nullable=True)
    robots = db.Column(db.String(64), nullable=False, default="index,follow")
    schema_json = db.Column(db.JSON, nullable=True)
    seo_excluded = db.Column(db.Boolean, nullable=False, default=False)

    # Layout / style / theme-switcher — mirrored from cms_page so a post can be
    # themed exactly like a page (same FK targets, nullability, and default).
    layout_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_layout.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    style_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_style.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Full-text search vector (S47.4). Postgres-maintained generated column —
    # never written by the app, never serialized in to_dict(). Queried by
    # SearchRepository via ``websearch_to_tsquery`` + ``ts_rank``.
    search_vector = db.Column(
        TSVECTOR,
        db.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
        nullable=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "type": self.type,
            "slug": self.slug,
            "title": self.title,
            "excerpt": self.excerpt,
            "featured_image_url": self.featured_image_url,
            "content_json": self.content_json,
            "content_html": self.content_html,
            "type_data": self.type_data,
            "author_id": str(self.author_id) if self.author_id else None,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "status": self.status,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "language": self.language,
            "translation_group_id": (
                str(self.translation_group_id) if self.translation_group_id else None
            ),
            "sort_order": self.sort_order,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "meta_keywords": self.meta_keywords,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image_url": self.og_image_url,
            "canonical_url": self.canonical_url,
            "robots": self.robots,
            "schema_json": self.schema_json,
            "seo_excluded": self.seo_excluded,
            "layout_id": str(self.layout_id) if self.layout_id else None,
            "style_id": str(self.style_id) if self.style_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CmsPost(type='{self.type}', slug='{self.slug}', status='{self.status}')>"
        )
