"""Add ``slug_base`` + ``primary_term_id`` to cms_post (S122 permalink engine).

Two nullable columns that feed the configurable post-permalink engine while the
``slug`` column keeps its full-path lookup semantics unchanged:

* ``slug_base`` (String(512)) — the post's OWN final path segment (``%slug%``).
  Backfilled to the last path segment of the existing ``slug`` so a going-forward
  re-render assembles the same tail. Nullable — pages/other types may leave it.
* ``primary_term_id`` (FK → cms_term.id, indexed) — the chosen primary category
  whose ancestor chain feeds ``%category%`` / ``%subcategory%`` / ``%category_path%``.
  ``ondelete=SET NULL`` so deleting a category never deletes the post.

Chains off the current cms head (20260706_cms_geo_block_config). This revision
becomes the new cms head, so the cms plugin's migration set resolves standalone.

Revision ID: 20260707_cms_post_permalink
Revises: 20260706_cms_geo_block_config
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260707_cms_post_permalink"
down_revision = "20260706_cms_geo_block_config"
branch_labels = None
depends_on = None


TABLE = "cms_post"
SLUG_BASE = "slug_base"
PRIMARY_TERM = "primary_term_id"
PRIMARY_TERM_INDEX = "ix_cms_post_primary_term_id"
PRIMARY_TERM_FK = "fk_cms_post_primary_term_id_cms_term"


def upgrade():
    # Idempotent guard: tolerate a dev DB whose alembic_version drifted or a
    # fresh create_all() that already built the columns from the model.
    conn = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(conn).get_columns(TABLE)}

    if SLUG_BASE not in existing_columns:
        op.add_column(TABLE, sa.Column(SLUG_BASE, sa.String(length=512), nullable=True))
        # Backfill: the post's own final segment = everything after the last "/".
        # A slug with no "/" is its own single segment (unchanged).
        op.execute(
            sa.text(
                f"UPDATE {TABLE} "
                f"SET {SLUG_BASE} = regexp_replace(slug, '^.*/', '') "
                f"WHERE {SLUG_BASE} IS NULL"
            )
        )

    if PRIMARY_TERM not in existing_columns:
        op.add_column(
            TABLE,
            sa.Column(PRIMARY_TERM, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_index(PRIMARY_TERM_INDEX, TABLE, [PRIMARY_TERM])
        op.create_foreign_key(
            PRIMARY_TERM_FK,
            TABLE,
            "cms_term",
            [PRIMARY_TERM],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    conn = op.get_bind()
    existing_columns = {col["name"] for col in sa.inspect(conn).get_columns(TABLE)}

    if PRIMARY_TERM in existing_columns:
        op.drop_constraint(PRIMARY_TERM_FK, TABLE, type_="foreignkey")
        op.drop_index(PRIMARY_TERM_INDEX, table_name=TABLE)
        op.drop_column(TABLE, PRIMARY_TERM)

    if SLUG_BASE in existing_columns:
        op.drop_column(TABLE, SLUG_BASE)
