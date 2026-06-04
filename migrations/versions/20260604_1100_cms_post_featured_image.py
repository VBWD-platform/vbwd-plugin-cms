"""Add ``featured_image_url`` to cms_post.

A post can carry a featured image (selected from / uploaded to the CMS image
gallery). Nullable string column; no FK — it stores the image's public URL,
matching how ``og_image_url`` is stored.

Chains off the current cms head (20260604_drop_theme_switcher). This revision
becomes the new cms head.

Revision ID: 20260604_cms_post_featured_image
Revises: 20260604_drop_theme_switcher
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260604_cms_post_featured_image"
down_revision = "20260604_drop_theme_switcher"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cms_post",
        sa.Column("featured_image_url", sa.String(length=512), nullable=True),
    )


def downgrade():
    op.drop_column("cms_post", "featured_image_url")
