"""Add ``config_override`` JSON column to cms_post_widget.

A per-page widget assignment may carry its OWN config override, edited in the
page editor's "Page widgets" section. The override is merged OVER the widget
record's shared ``config`` at render time, for that post only. Nullable JSON
column; ``None`` means "use the widget's default config unchanged". Layout-level
assignments (``cms_layout_widget``) are unaffected.

Chains off the current cms head (20260613_1300_fold_tags). This revision
becomes the new cms head.

Revision ID: 20260617_cms_pw_config_override
Revises: 20260613_1300_fold_tags
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa


revision = "20260617_cms_pw_config_override"
down_revision = "20260613_1300_fold_tags"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cms_post_widget",
        sa.Column("config_override", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("cms_post_widget", "config_override")
