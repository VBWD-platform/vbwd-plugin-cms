"""Add is_default flag + partial unique index to cms_layout.

Revision ID: 20260606_1100_cms_layout_default
Revises: 20260606_cms_post_areas_widgets
Create Date: 2026-06-06

Default-layout feature — mirrors 20260420_1000_style_default for cms_style.
Replaces the (removed) ``default_layout_id`` plugin-config approach.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260606_1100_cms_layout_default"
down_revision = "20260606_cms_post_areas_widgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: guard against a column/index already present (e.g. a dev DB
    # whose alembic_version drifted), mirroring the style-default migration.
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_columns = {col["name"] for col in inspector.get_columns("cms_layout")}
    if "is_default" not in existing_columns:
        op.add_column(
            "cms_layout",
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Partial unique index: at most one row may have is_default=TRUE.
    # Any attempt to promote a second row outside the service fails.
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("cms_layout")}
    if "ix_cms_layout_default_singleton" not in existing_indexes:
        op.create_index(
            "ix_cms_layout_default_singleton",
            "cms_layout",
            ["is_default"],
            unique=True,
            postgresql_where=sa.text("is_default IS TRUE"),
        )

    # Drop the server_default once the column is seeded; the ORM owns the
    # default via the model definition.
    op.alter_column("cms_layout", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_cms_layout_default_singleton", table_name="cms_layout")
    op.drop_column("cms_layout", "is_default")
