"""Add is_default flag + partial unique index to cms_style.

Revision ID: 20260420_1000_cms_style_is_default
Revises: 20260412_1000
Create Date: 2026-04-20

Sprint 26 — default-style feature.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260420_1000_style_default"
down_revision = "20260412_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: prod instances received this column + index from an
    # earlier revision of this migration before it was relocated into the
    # cms plugin during the 2026-05-25 migration-graph rework, so their
    # alembic_version no longer records this revision while the schema
    # already reflects it. Re-running plain ADD COLUMN raised
    # DuplicateColumn and crashed api startup on 2026-05-26.
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_columns = {col["name"] for col in inspector.get_columns("cms_style")}
    if "is_default" not in existing_columns:
        op.add_column(
            "cms_style",
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Partial unique index: at most one row may have is_default=TRUE.
    # Any attempt to promote a second row outside the service fails.
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("cms_style")}
    if "ix_cms_style_default_singleton" not in existing_indexes:
        op.create_index(
            "ix_cms_style_default_singleton",
            "cms_style",
            ["is_default"],
            unique=True,
            postgresql_where=sa.text("is_default IS TRUE"),
        )

    # Drop the server_default once the column is seeded; the ORM will
    # now own the default via the model definition. alter_column is
    # idempotent — re-applying server_default=None on a column that
    # already has no default is a no-op.
    op.alter_column("cms_style", "is_default", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_cms_style_default_singleton", table_name="cms_style")
    op.drop_column("cms_style", "is_default")
