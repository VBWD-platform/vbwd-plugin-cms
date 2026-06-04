"""Add the FTS search_vector generated column + GIN index to cms_post (S47.4).

Additive only. A weighted ``tsvector`` GENERATED ALWAYS column over
title (A) / excerpt (B) / HTML-stripped content_html (C), plus a GIN index,
so published-post full-text search ranks title hits above body hits. The
generated column keeps itself correct on every write — no trigger code.

The weighting expression is the single source of truth shared with the
CmsPost model (``SEARCH_VECTOR_EXPRESSION``) so create_all() and this
migration produce identical DDL (DRY).

Chains off the cms unified-post head (20260603_1000_cms_unified) so it
resolves standalone within the cms plugin's own migration set.

Revision ID: 20260603_1100_cms_search_vec
Revises: 20260603_1000_cms_unified
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

from plugins.cms.src.models.cms_post import (
    SEARCH_VECTOR_EXPRESSION,
    SEARCH_VECTOR_INDEX,
)


revision = "20260603_1100_cms_search_vec"
down_revision = "20260603_1000_cms_unified"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cms_post",
        sa.Column(
            "search_vector",
            TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_EXPRESSION, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        SEARCH_VECTOR_INDEX,
        "cms_post",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade():
    op.drop_index(SEARCH_VECTOR_INDEX, table_name="cms_post")
    op.drop_column("cms_post", "search_vector")
