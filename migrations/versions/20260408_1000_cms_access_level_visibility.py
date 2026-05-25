"""Add required_access_level_ids to cms_layout_widget and cms_page.

Sprint 18a: Access-level-driven content visibility.

Revision ID: 20260408_1000
Revises: 20260406_1800
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260408_1000"
down_revision = "20260406_1800"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    if not _column_exists(conn, "cms_layout_widget", "required_access_level_ids"):
        op.add_column(
            "cms_layout_widget",
            sa.Column(
                "required_access_level_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    if not _column_exists(conn, "cms_page", "required_access_level_ids"):
        op.add_column(
            "cms_page",
            sa.Column(
                "required_access_level_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade():
    op.drop_column("cms_page", "required_access_level_ids")
    op.drop_column("cms_layout_widget", "required_access_level_ids")


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.scalar() is not None
