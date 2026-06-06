"""Add ``preview_token`` to cms_post.

A capability token (random hex) lets an admin preview an unpublished post via a
shareable ``?preview_token=…`` URL — the public route returns the post
regardless of status when the token matches. Nullable, indexed; mirrors
``cms_page.preview_token``.

Chains off the current cms head (20260604_cms_post_source_css). This revision
becomes the new cms head.

Revision ID: 20260605_cms_post_preview_token
Revises: 20260604_cms_post_source_css
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa


revision = "20260605_cms_post_preview_token"
down_revision = "20260604_cms_post_source_css"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cms_post", sa.Column("preview_token", sa.String(length=64), nullable=True)
    )
    op.create_index("ix_cms_post_preview_token", "cms_post", ["preview_token"])


def downgrade():
    op.drop_index("ix_cms_post_preview_token", table_name="cms_post")
    op.drop_column("cms_post", "preview_token")
