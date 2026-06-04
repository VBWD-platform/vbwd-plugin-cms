"""Drop the legacy ``use_theme_switcher_styles`` flag from cms_post + cms_page.

The theme-switcher opt-out is removed: public pages/posts now always render the
resolved style (explicit ``style_id`` else the admin-designated default) with the
page's own ``source_css`` layered on top. The boolean column no longer has any
consumer, so it is dropped from both content tables.

Chains off the current cms head (20260603_1200_cms_post_layout) so it resolves
standalone within the cms plugin's own migration set. This revision becomes the
new cms head.

Revision ID: 20260604_drop_theme_switcher
Revises: 20260603_1200_cms_post_layout
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260604_drop_theme_switcher"
down_revision = "20260603_1200_cms_post_layout"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("cms_post", "use_theme_switcher_styles")
    op.drop_column("cms_page", "use_theme_switcher_styles")


def downgrade():
    op.add_column(
        "cms_page",
        sa.Column(
            "use_theme_switcher_styles",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "cms_post",
        sa.Column(
            "use_theme_switcher_styles",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
