"""Drop ``is_global`` from cms_widget.

The site-wide "global widget" injection was the wrong approach and is removed
entirely (the column, route, service, repo and exchanger field all go). This
migration drops the column. ``down()`` re-adds it nullable/default-false so the
revision stays reversible.

Chains off the prior cms head (20260612_1000_cms_widget_global) and becomes the
new cms head. Idempotent/guarded so a drifted dev DB upgrades cleanly.

Revision ID: 20260612_1100_drop_widget_global
Revises: 20260612_1000_cms_widget_global
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260612_1100_drop_widget_global"
down_revision = "20260612_1000_cms_widget_global"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("cms_widget")}
    if "is_global" in existing_columns:
        op.drop_column("cms_widget", "is_global")


def downgrade() -> None:
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
        # The model previously owned the default; drop the server_default once
        # existing rows are backfilled to false (mirrors the original add).
        op.alter_column("cms_widget", "is_global", server_default=None)
