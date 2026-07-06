"""Create ``cms_geo_block_config`` singleton table (S120).

A one-row settings table for CMS country geo-blocking: master switch, the bypass
query + cookie TTL, the blocked-visitor target slug, and the unknown-country
policy. The allowed-country ISO set is NOT stored here — it is derived live from
core ``vbwd_country.is_enabled`` (DRY).

Chains off the current cms head (20260705_cms_layout_head_html). This revision
becomes the new cms head, so it resolves standalone within the cms plugin's own
migration set.

Revision ID: 20260706_cms_geo_block_config
Revises: 20260705_cms_layout_head_html
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260706_cms_geo_block_config"
down_revision = "20260705_cms_layout_head_html"
branch_labels = None
depends_on = None


TABLE = "cms_geo_block_config"


def upgrade():
    # Idempotent guard: tolerate a dev DB whose alembic_version drifted.
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE in inspector.get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "bypass_query", sa.String(length=255), nullable=False, server_default=""
        ),
        sa.Column(
            "bypass_cookie_ttl_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "blocked_target_slug",
            sa.String(length=255),
            nullable=False,
            server_default="/locked",
        ),
        sa.Column(
            "block_unknown_country",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_table(TABLE)
