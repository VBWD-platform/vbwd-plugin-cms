"""Backfill cms_page.slug with the full URL path (category_slug/page_slug).

Option B of the nested-URL fix: pages keep a single `slug` column but
store the full path — "features/cms-module" instead of "cms-module" with
a separate category lookup. Lookup by URL becomes a direct column match.

Only rows that have a category AND whose current slug has no slash are
prefixed. Flat pages and already-prefixed slugs are left alone, so the
migration is idempotent across re-runs and across pages created after
the new service logic landed.

Revision ID: 20260422_1200
Revises: 20260420_1000_style_default
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "20260422_1200"
down_revision = "20260420_1000_style_default"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if not _table_exists(conn, "cms_page") or not _table_exists(conn, "cms_category"):
        return

    conn.execute(
        sa.text(
            """
            UPDATE cms_page AS page
               SET slug = category.slug || '/' || page.slug
              FROM cms_category AS category
             WHERE page.category_id = category.id
               AND position('/' in page.slug) = 0
            """
        )
    )


def downgrade():
    conn = op.get_bind()
    if not _table_exists(conn, "cms_page"):
        return

    conn.execute(
        sa.text(
            """
            UPDATE cms_page
               SET slug = split_part(slug, '/', -1)
             WHERE category_id IS NOT NULL
               AND position('/' in slug) > 0
            """
        )
    )


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables " "WHERE table_name = :name"),
        {"name": table_name},
    )
    return result.scalar() is not None
