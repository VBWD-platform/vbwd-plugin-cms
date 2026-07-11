"""Create ``cms_entity_page`` — the entity-page attachment link table (S128).

A small link table mapping an opaque owning entity (``owner_type`` +
``owner_id``, one page per ``slot``) to a ``cms_post`` (``type=entity_page``).
An entity page reuses the whole CMS content stack; this is the ONLY new storage.
Keeping the link in its own table (not owner columns on cms_post, not a
page_post_id on each entity) preserves SRP and means zero schema change in any
adopter plugin.

Additive / non-destructive: a new table only, no change to existing rows.
``UNIQUE(owner_type, owner_id, slot)`` enforces one page per owner+slot; an
index on ``(owner_type, owner_id)`` backs the lookup. ``post_id`` cascades on
post delete. Chains off the current cms head (20260708_cms_post_pinned); this
revision becomes the new cms head, so the cms plugin's migration set still
resolves standalone.

Engineering requirements (binding, restated): TDD-first (migration proven by an
up/down/up integration test); DevOps-first (schema only via Alembic, chained
within the cms plugin's own migration set, validated up→down→up); SOLID (SRP —
the link is separate from the post); DI/DRY; Liskov; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.

Revision ID: 20260711_cms_entity_page
Revises: 20260708_cms_post_pinned
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260711_cms_entity_page"
down_revision = "20260708_cms_post_pinned"
branch_labels = None
depends_on = None


TABLE = "cms_entity_page"
OWNER_INDEX = "ix_cms_entity_page_owner"
POST_ID_INDEX = "ix_cms_entity_page_post_id"


def upgrade():
    # Idempotent guard: tolerate a dev DB whose alembic_version drifted or a
    # fresh create_all() that already built the table from the model.
    conn = op.get_bind()
    if TABLE in sa.inspect(conn).get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner_type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("slot", sa.String(length=64), nullable=False, server_default="main"),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cms_post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "owner_type", "owner_id", "slot", name="uq_cms_entity_page_owner_slot"
        ),
    )
    op.create_index(OWNER_INDEX, TABLE, ["owner_type", "owner_id"])
    op.create_index(POST_ID_INDEX, TABLE, ["post_id"])


def downgrade():
    conn = op.get_bind()
    if TABLE not in sa.inspect(conn).get_table_names():
        return
    op.drop_index(POST_ID_INDEX, table_name=TABLE)
    op.drop_index(OWNER_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
