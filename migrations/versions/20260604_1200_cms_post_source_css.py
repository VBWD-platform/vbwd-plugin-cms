"""Add ``source_css`` to cms_post.

A post/page can carry its own CSS (authored on the editor's "CSS" tab), applied
on top of the resolved style by the public renderer and travelling with
export/import. Nullable text column, mirroring ``cms_page.source_css``.

Chains off the current cms head (20260604_cms_post_featured_image). This
revision becomes the new cms head.

Revision ID: 20260604_cms_post_source_css
Revises: 20260604_cms_post_featured_image
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260604_cms_post_source_css"
down_revision = "20260604_cms_post_featured_image"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cms_post", sa.Column("source_css", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("cms_post", "source_css")
