"""Refactor cms_widget: drop content_html, add source_css, migrate HTML to content_json base64.

HTML widgets previously stored content in content_html (raw HTML+styles mixed).
New structure:
  - content_json = {"content": "<base64-encoded HTML without inline styles>"}
  - source_css   = extracted CSS text

Revision ID: 20260308_cms_widget_refactor
Revises: 20260308_cms_page_content_html
Create Date: 2026-03-08 13:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "20260308_cms_widget_refactor"
down_revision: Union[str, None] = "20260308_cms_page_content_html"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add source_css
    op.add_column("cms_widget", sa.Column("source_css", sa.Text, nullable=True))

    # 2. Migrate content_html → content_json {"content": base64(html)}
    #    Only for html-type widgets that have non-null content_html.
    #    PostgreSQL encode(bytea, 'base64') produces standard base64.
    op.execute(text("""
        UPDATE cms_widget
        SET content_json = jsonb_build_object(
            'content',
            replace(encode(convert_to(content_html, 'UTF8'), 'base64'), E'\n', '')
        )
        WHERE widget_type = 'html'
          AND content_html IS NOT NULL
          AND content_html <> ''
    """))

    # 3. Drop content_html
    op.drop_column("cms_widget", "content_html")


def downgrade() -> None:
    # Re-add content_html
    op.add_column("cms_widget", sa.Column("content_html", sa.Text, nullable=True))

    # Restore from base64 content_json
    op.execute(text("""
        UPDATE cms_widget
        SET content_html = convert_from(
            decode(content_json->>'content', 'base64'), 'UTF8'
        )
        WHERE widget_type = 'html'
          AND content_json ? 'content'
          AND content_json->>'content' IS NOT NULL
    """))

    op.drop_column("cms_widget", "source_css")
