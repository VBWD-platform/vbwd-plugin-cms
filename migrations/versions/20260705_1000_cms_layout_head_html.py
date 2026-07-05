"""Add ``head_html`` to cms_layout.

A layout can carry a raw HTML snippet (scripts, styles, meta/link tags) that the
public app injects before ``</head>`` on every page using that layout. Authored
on the layout editor's "<head>" block and travelling with export/import.
Nullable text column.

Chains off the current cms head (20260625_drop_legacy_cms_page). This revision
becomes the new cms head, so it resolves standalone within the cms plugin's own
migration set.

Revision ID: 20260705_cms_layout_head_html
Revises: 20260625_drop_legacy_cms_page
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = "20260705_cms_layout_head_html"
down_revision = "20260625_drop_legacy_cms_page"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent guard: tolerate a dev DB whose alembic_version drifted.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("cms_layout")}
    if "head_html" not in existing_columns:
        op.add_column("cms_layout", sa.Column("head_html", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("cms_layout", "head_html")
