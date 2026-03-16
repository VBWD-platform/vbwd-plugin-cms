"""Add source_css column to cms_page.

Revision ID: 20260308_cms_page_source_css
Revises: 20260308_cms_widget_refactor
Create Date: 2026-03-08 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260308_cms_page_source_css"
down_revision: Union[str, None] = "20260308_cms_widget_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cms_page",
        sa.Column("source_css", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_page", "source_css")
