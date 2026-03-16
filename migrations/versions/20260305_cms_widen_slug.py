"""Widen cms_page.slug to VARCHAR(512) to support multi-segment paths.

Revision ID: 20260305_cms_widen_slug
Revises: 20260302_cms_tables
Create Date: 2026-03-05 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260305_cms_widen_slug"
down_revision: Union[str, None] = "20260302_cms_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "cms_page",
        "slug",
        existing_type=sa.String(128),
        type_=sa.String(512),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "cms_page",
        "slug",
        existing_type=sa.String(512),
        type_=sa.String(128),
        existing_nullable=False,
    )
