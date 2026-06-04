"""Add layout/style/theme-switcher to cms_post (posts like pages).

Additive only. Gives ``cms_post`` the same layout/style capability ``cms_page``
already has (user feedback: "posts must have theme style and layout, same like
pages"):
  - ``layout_id``  UUID FK → cms_layout.id, nullable, ON DELETE SET NULL
  - ``style_id``   UUID FK → cms_style.id,  nullable, ON DELETE SET NULL
  - ``use_theme_switcher_styles`` Boolean, NOT NULL, default true

FK targets and nullability mirror cms_page exactly. Chains off the current cms
head (20260603_1100_cms_search_vec) so it resolves standalone within the cms
plugin's own migration set — no anchoring on an unrelated plugin. This revision
becomes the new cms head.

Revision ID: 20260603_1200_cms_post_layout
Revises: 20260603_1100_cms_search_vec
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260603_1200_cms_post_layout"
down_revision = "20260603_1100_cms_search_vec"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cms_post",
        sa.Column("layout_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "cms_post",
        sa.Column("style_id", postgresql.UUID(as_uuid=True), nullable=True),
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
    op.create_index("ix_cms_post_layout_id", "cms_post", ["layout_id"])
    op.create_index("ix_cms_post_style_id", "cms_post", ["style_id"])
    op.create_foreign_key(
        "fk_cms_post_layout_id",
        "cms_post",
        "cms_layout",
        ["layout_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_cms_post_style_id",
        "cms_post",
        "cms_style",
        ["style_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_cms_post_style_id", "cms_post", type_="foreignkey")
    op.drop_constraint("fk_cms_post_layout_id", "cms_post", type_="foreignkey")
    op.drop_index("ix_cms_post_style_id", table_name="cms_post")
    op.drop_index("ix_cms_post_layout_id", table_name="cms_post")
    op.drop_column("cms_post", "use_theme_switcher_styles")
    op.drop_column("cms_post", "style_id")
    op.drop_column("cms_post", "layout_id")
