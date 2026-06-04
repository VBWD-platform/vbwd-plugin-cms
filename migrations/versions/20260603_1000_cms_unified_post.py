"""Create the unified content tables: cms_post, cms_term, cms_post_term (S47.0).

Additive only — does NOT touch cms_page / cms_category. The cms_page →
cms_post(type=page) backfill is a later run. Chains off the current cms
head (20260422_1200) so it resolves standalone with the cms plugin's own
migration set, no anchoring on an unrelated plugin.

Revision ID: 20260603_1000_cms_unified
Revises: 20260422_1200
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260603_1000_cms_unified"
down_revision = "20260422_1200"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cms_post",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("type_data", sa.JSON(), nullable=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("translation_group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_keywords", sa.Text(), nullable=True),
        sa.Column("og_title", sa.String(length=255), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image_url", sa.String(length=512), nullable=True),
        sa.Column("canonical_url", sa.String(length=512), nullable=True),
        sa.Column(
            "robots",
            sa.String(length=64),
            nullable=False,
            server_default="index,follow",
        ),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column(
            "seo_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.ForeignKeyConstraint(["author_id"], ["vbwd_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["cms_post.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("type", "slug", name="uq_cms_post_type_slug"),
    )
    op.create_index("ix_cms_post_type", "cms_post", ["type"])
    op.create_index("ix_cms_post_slug", "cms_post", ["slug"])
    op.create_index("ix_cms_post_parent_id", "cms_post", ["parent_id"])
    op.create_index("ix_cms_post_status", "cms_post", ["status"])
    op.create_index(
        "ix_cms_post_translation_group_id", "cms_post", ["translation_group_id"]
    )

    op.create_table(
        "cms_term",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("term_type", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "seo_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["parent_id"], ["cms_term.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("term_type", "slug", name="uq_cms_term_type_slug"),
    )
    op.create_index("ix_cms_term_term_type", "cms_term", ["term_type"])
    op.create_index("ix_cms_term_slug", "cms_term", ["slug"])
    op.create_index("ix_cms_term_parent_id", "cms_term", ["parent_id"])

    op.create_table(
        "cms_post_term",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["cms_post.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["term_id"], ["cms_term.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("post_id", "term_id", name="uq_cms_post_term"),
    )
    op.create_index("ix_cms_post_term_post_id", "cms_post_term", ["post_id"])
    op.create_index("ix_cms_post_term_term_id", "cms_post_term", ["term_id"])


def downgrade():
    op.drop_index("ix_cms_post_term_term_id", table_name="cms_post_term")
    op.drop_index("ix_cms_post_term_post_id", table_name="cms_post_term")
    op.drop_table("cms_post_term")

    op.drop_index("ix_cms_term_parent_id", table_name="cms_term")
    op.drop_index("ix_cms_term_slug", table_name="cms_term")
    op.drop_index("ix_cms_term_term_type", table_name="cms_term")
    op.drop_table("cms_term")

    op.drop_index("ix_cms_post_translation_group_id", table_name="cms_post")
    op.drop_index("ix_cms_post_status", table_name="cms_post")
    op.drop_index("ix_cms_post_parent_id", table_name="cms_post")
    op.drop_index("ix_cms_post_slug", table_name="cms_post")
    op.drop_index("ix_cms_post_type", table_name="cms_post")
    op.drop_table("cms_post")
