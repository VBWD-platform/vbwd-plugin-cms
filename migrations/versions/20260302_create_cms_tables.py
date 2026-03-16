"""Create CMS plugin tables: cms_category, cms_page, cms_image.

Revision ID: 20260302_cms_tables
Revises: m4n5o6p7q8r9
Create Date: 2026-03-02 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260302_cms_tables"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── cms_category ─────────────────────────────────────────────────────────
    op.create_table(
        "cms_category",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "parent_id",
            sa.UUID(),
            sa.ForeignKey("cms_category.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cms_category_slug", "cms_category", ["slug"], unique=True)
    op.create_index(
        "ix_cms_category_parent_id", "cms_category", ["parent_id"], unique=False
    )

    # ── cms_page ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_page",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column(
            "category_id",
            sa.UUID(),
            sa.ForeignKey("cms_category.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        # SEO
        sa.Column("meta_title", sa.String(255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_keywords", sa.Text(), nullable=True),
        sa.Column("og_title", sa.String(255), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image_url", sa.String(512), nullable=True),
        sa.Column("canonical_url", sa.String(512), nullable=True),
        sa.Column(
            "robots", sa.String(64), nullable=False, server_default="index,follow"
        ),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cms_page_slug", "cms_page", ["slug"], unique=True)
    op.create_index(
        "ix_cms_page_category_id", "cms_page", ["category_id"], unique=False
    )

    # ── cms_image ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_image",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("caption", sa.String(255), nullable=True),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("url_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        # SEO
        sa.Column("alt_text", sa.String(255), nullable=True),
        sa.Column("og_image_url", sa.String(512), nullable=True),
        sa.Column("robots", sa.String(64), nullable=True),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cms_image_slug", "cms_image", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_cms_image_slug", "cms_image")
    op.drop_table("cms_image")

    op.drop_index("ix_cms_page_category_id", "cms_page")
    op.drop_index("ix_cms_page_slug", "cms_page")
    op.drop_table("cms_page")

    op.drop_index("ix_cms_category_parent_id", "cms_category")
    op.drop_index("ix_cms_category_slug", "cms_category")
    op.drop_table("cms_category")
