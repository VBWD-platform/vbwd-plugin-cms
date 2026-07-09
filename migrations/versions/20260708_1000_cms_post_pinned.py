"""Add ``pinned`` to cms_post + cms_post_term (pinned/sticky archives).

Two additive, non-destructive boolean columns that power the "pin a post to the
top of a listing" feature:

* ``cms_post.pinned`` (Boolean NOT NULL, server_default false) — the site-wide
  pin used by the ``/{posts_root}`` blog index. A pinned post floats to the top
  of the blog listing ahead of the normal ordering.
* ``cms_post_term.pinned`` (Boolean NOT NULL, server_default false) — the
  per-category pin. A post pinned within a category floats to the top of that
  category's archive (``/category/<slug>``), scoped to that single post↔term link.

Both default False, so every existing row is unaffected (nothing pinned until an
admin opts in). Chains off the current cms head (20260707_cms_post_permalink);
this revision becomes the new cms head, so the cms plugin's migration set still
resolves standalone.

Engineering requirements (binding, restated): TDD-first (migration proven by an
up/down/up integration test); DevOps-first (schema only via Alembic, chained
within the cms plugin's own migration set, validated up→down→up); SOLID/DI/DRY;
Liskov (default False = the "not pinned" contract existing rows imply); no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.

Revision ID: 20260708_cms_post_pinned
Revises: 20260707_cms_post_permalink
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "20260708_cms_post_pinned"
down_revision = "20260707_cms_post_permalink"
branch_labels = None
depends_on = None


POST_TABLE = "cms_post"
POST_TERM_TABLE = "cms_post_term"
PINNED = "pinned"


def _has_column(conn, table: str, column: str) -> bool:
    return column in {col["name"] for col in sa.inspect(conn).get_columns(table)}


def upgrade():
    # Idempotent guard: tolerate a dev DB whose alembic_version drifted or a
    # fresh create_all() that already built the columns from the model.
    conn = op.get_bind()

    if not _has_column(conn, POST_TABLE, PINNED):
        op.add_column(
            POST_TABLE,
            sa.Column(
                PINNED,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if not _has_column(conn, POST_TERM_TABLE, PINNED):
        op.add_column(
            POST_TERM_TABLE,
            sa.Column(
                PINNED,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade():
    conn = op.get_bind()

    if _has_column(conn, POST_TERM_TABLE, PINNED):
        op.drop_column(POST_TERM_TABLE, PINNED)

    if _has_column(conn, POST_TABLE, PINNED):
        op.drop_column(POST_TABLE, PINNED)
