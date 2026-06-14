"""Add ``is_global`` to cms_widget.

A widget marked global renders on EVERY public page regardless of layout — the
home for a site-wide analytics/gtag snippet. Boolean, default false, not null.

Chains off the current cms head (20260606_1100_cms_layout_default). This
revision becomes the new cms head. Idempotent/guarded: skips the add when a
drifted dev DB already carries the column.

Revision ID: 20260612_1000_cms_widget_global
Revises: 20260606_1100_cms_layout_default
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260612_1000_cms_widget_global"
down_revision = "20260606_1100_cms_layout_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("cms_widget")}
    if "is_global" not in existing_columns:
        op.add_column(
            "cms_widget",
            sa.Column(
                "is_global",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        # The ORM owns the default via the model; drop the server_default once
        # existing rows are backfilled to false.
        op.alter_column("cms_widget", "is_global", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("cms_widget")}
    if "is_global" in existing_columns:
        op.drop_column("cms_widget", "is_global")
