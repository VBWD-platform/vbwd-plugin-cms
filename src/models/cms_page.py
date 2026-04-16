"""CmsPage model — rich-text content page with SEO metadata."""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class CmsPage(BaseModel):
    """A single CMS content page stored as TipTap JSON."""

    __tablename__ = "cms_page"

    slug = db.Column(db.String(512), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    language = db.Column(db.String(8), nullable=False, default="en")
    content_json = db.Column(db.JSON, nullable=False, default=dict)
    content_html = db.Column(db.Text, nullable=True)
    source_css = db.Column(db.Text, nullable=True)
    category_id = db.Column(
        db.UUID,
        db.ForeignKey("cms_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    # SEO
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    meta_keywords = db.Column(db.Text, nullable=True)
    og_title = db.Column(db.String(255), nullable=True)
    og_description = db.Column(db.Text, nullable=True)
    og_image_url = db.Column(db.String(512), nullable=True)
    canonical_url = db.Column(db.String(512), nullable=True)
    robots = db.Column(db.String(64), nullable=False, default="index,follow")
    schema_json = db.Column(db.JSON, nullable=True)

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
    use_theme_switcher_styles = db.Column(db.Boolean, nullable=False, default=True)
    preview_token = db.Column(db.String(64), nullable=True, index=True)
    required_access_level_ids = db.Column(db.JSON, nullable=False, default=list)

    category = db.relationship(
        "CmsCategory",
        backref="pages",
        foreign_keys=[category_id],
        lazy="selectin",
    )

    content_blocks = db.relationship(
        "CmsPageContentBlock",
        backref="page",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="CmsPageContentBlock.sort_order",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "language": self.language,
            "content_json": self.content_json,
            "content_html": self.content_html,
            "source_css": self.source_css,
            "category_id": str(self.category_id) if self.category_id else None,
            "is_published": self.is_published,
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
            "layout_id": str(self.layout_id) if self.layout_id else None,
            "style_id": str(self.style_id) if self.style_id else None,
            "use_theme_switcher_styles": self.use_theme_switcher_styles,
            "preview_token": self.preview_token,
            "required_access_level_ids": self.required_access_level_ids or [],
            "content_blocks": {
                block.area_name: block.to_dict()
                for block in list(self.content_blocks or [])
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsPage(slug='{self.slug}', published={self.is_published})>"
