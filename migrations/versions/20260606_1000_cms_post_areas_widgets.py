"""Add cms_post_widget + cms_post_content_block tables (S55).

Mirrors the legacy cms_page_widget / cms_page_content_block features onto the
unified cms_post: per-post widget overrides and multiple content areas.

Anchored on the latest cms plugin revision so the cms migration chain resolves
standalone (no cross-plugin anchor — see the migration-graph discipline).

Revision ID: 20260606_cms_post_areas_widgets
Revises: 20260605_cms_post_preview_token
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260606_cms_post_areas_widgets"
down_revision = "20260605_cms_post_preview_token"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, "cms_post_widget"):
        op.create_table(
            "cms_post_widget",
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "post_id",
                UUID(as_uuid=True),
                sa.ForeignKey("cms_post.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "widget_id",
                UUID(as_uuid=True),
                sa.ForeignKey("cms_widget.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("area_name", sa.String(64), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "required_access_level_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_cms_post_widget_post_id", "cms_post_widget", ["post_id"])
        op.create_index(
            "ix_cms_post_widget_widget_id", "cms_post_widget", ["widget_id"]
        )

    if not _table_exists(conn, "cms_post_content_block"):
        op.create_table(
            "cms_post_content_block",
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "post_id",
                UUID(as_uuid=True),
                sa.ForeignKey("cms_post.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("area_name", sa.String(100), nullable=False),
            sa.Column("content_json", sa.JSON(), nullable=True),
            sa.Column("content_html", sa.Text(), nullable=True),
            sa.Column("source_css", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "post_id", "area_name", name="uq_post_content_block_area"
            ),
        )
        op.create_index(
            "ix_cms_post_content_block_post_id",
            "cms_post_content_block",
            ["post_id"],
        )


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, "cms_post_content_block"):
        op.drop_index(
            "ix_cms_post_content_block_post_id",
            table_name="cms_post_content_block",
        )
        op.drop_table("cms_post_content_block")
    if _table_exists(conn, "cms_post_widget"):
        op.drop_index("ix_cms_post_widget_widget_id", table_name="cms_post_widget")
        op.drop_index("ix_cms_post_widget_post_id", table_name="cms_post_widget")
        op.drop_table("cms_post_widget")


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables " "WHERE table_name = :name"),
        {"name": table_name},
    )
    return result.scalar() is not None
