"""Add cms_page_widget table for page-level widget assignments.

Sprint 19: Page-defined widgets.

Revision ID: 20260412_1000
Revises: 20260408_1000
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260412_1000"
down_revision = "20260408_1000"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if _table_exists(conn, "cms_page_widget"):
        return

    op.create_table(
        "cms_page_widget",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "page_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cms_page.id", ondelete="CASCADE"),
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
    op.create_index("ix_cms_page_widget_page_id", "cms_page_widget", ["page_id"])
    op.create_index("ix_cms_page_widget_widget_id", "cms_page_widget", ["widget_id"])


def downgrade():
    op.drop_index("ix_cms_page_widget_widget_id", table_name="cms_page_widget")
    op.drop_index("ix_cms_page_widget_page_id", table_name="cms_page_widget")
    op.drop_table("cms_page_widget")


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables " "WHERE table_name = :name"),
        {"name": table_name},
    )
    return result.scalar() is not None
