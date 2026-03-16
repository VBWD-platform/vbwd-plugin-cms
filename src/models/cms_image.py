"""CmsImage model — uploaded media file with SEO metadata."""
from src.extensions import db
from src.models.base import BaseModel


class CmsImage(BaseModel):
    """An uploaded image or video file managed through the CMS gallery."""

    __tablename__ = "cms_image"

    slug = db.Column(db.String(128), unique=True, nullable=False, index=True)
    caption = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(512), nullable=False)   # relative to uploads root
    url_path = db.Column(db.String(512), nullable=False)    # e.g. /uploads/images/foo.jpg
    mime_type = db.Column(db.String(64), nullable=True)
    file_size_bytes = db.Column(db.Integer, nullable=True)
    width_px = db.Column(db.Integer, nullable=True)
    height_px = db.Column(db.Integer, nullable=True)

    # SEO
    alt_text = db.Column(db.String(255), nullable=True)
    og_image_url = db.Column(db.String(512), nullable=True)
    robots = db.Column(db.String(64), nullable=True)
    schema_json = db.Column(db.JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "caption": self.caption,
            "file_path": self.file_path,
            "url_path": self.url_path,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "alt_text": self.alt_text,
            "og_image_url": self.og_image_url,
            "robots": self.robots,
            "schema_json": self.schema_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CmsImage(slug='{self.slug}', mime='{self.mime_type}')>"
