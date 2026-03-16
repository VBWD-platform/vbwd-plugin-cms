"""Add content_html column to cms_page.

Revision ID: 20260308_cms_page_content_html
Revises: 20260305_cms_templates
Create Date: 2026-03-08 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260308_cms_page_content_html"
down_revision: Union[str, None] = "20260305_cms_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cms_page",
        sa.Column("content_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cms_page", "content_html")
