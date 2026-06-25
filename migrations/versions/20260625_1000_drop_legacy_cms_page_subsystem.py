"""S105 — drop the legacy cms_page + cms_category subsystem.

The unified ``cms_post`` (pages+posts) / ``cms_term`` (categories+tags) model is
now the single source of truth. The legacy content tables — ``cms_page``,
``cms_category`` and the two ``cms_page``-dependent assignment tables
(``cms_page_widget``, ``cms_page_content_block``) — have no remaining reader and
are retired here.

``upgrade()`` drops the four tables in FK-safe order (children before parents),
guarded with ``IF EXISTS`` so a partial/legacy-free database is tolerated.

``downgrade()`` recreates them with their original columns + foreign keys so the
graph stays reversible. It restores SCHEMA only (no data) — the legacy rows were
already folded into the unified model before this slice, so a rollback never
needs to reconstruct content.

Revision ID: 20260625_drop_legacy_cms_page
Revises: 20260618_unfold_tags
Create Date: 2026-06-25

A CMS-plugin migration. Chains linearly off the current cms head
(``20260618_unfold_tags``) and becomes the new cms head, so it resolves
standalone within the cms plugin's own migration set.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID


revision = "20260625_drop_legacy_cms_page"
down_revision = "20260618_unfold_tags"
branch_labels = None
depends_on = None


def upgrade():
    # FK-safe order: the two assignment tables reference cms_page; cms_page
    # references cms_category. Drop children first, then cms_page, then
    # cms_category. IF EXISTS keeps a legacy-free DB (e.g. a fresh standalone
    # plugin install that never had these tables) safe.
    op.execute("DROP TABLE IF EXISTS cms_page_widget CASCADE")
    op.execute("DROP TABLE IF EXISTS cms_page_content_block CASCADE")
    op.execute("DROP TABLE IF EXISTS cms_page CASCADE")
    op.execute("DROP TABLE IF EXISTS cms_category CASCADE")


def downgrade():
    # Recreate cms_category first (cms_page FKs it), then cms_page, then the two
    # assignment tables. Columns mirror the retired models' final shape so the
    # rollback restores a structurally identical schema (data is not restored).
    op.create_table(
        "cms_category",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["cms_category.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_cms_category_slug", "cms_category", ["slug"], unique=True)
    op.create_index("ix_cms_category_parent_id", "cms_category", ["parent_id"])

    op.create_table(
        "cms_page",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("slug", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("content_json", JSON(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("source_css", sa.Text(), nullable=True),
        sa.Column("category_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_published", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_keywords", sa.Text(), nullable=True),
        sa.Column("og_title", sa.String(length=255), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image_url", sa.String(length=512), nullable=True),
        sa.Column("canonical_url", sa.String(length=512), nullable=True),
        sa.Column(
            "robots",
            sa.String(length=64),
            nullable=False,
            server_default="index,follow",
        ),
        sa.Column("schema_json", JSON(), nullable=True),
        sa.Column("layout_id", UUID(as_uuid=True), nullable=True),
        sa.Column("style_id", UUID(as_uuid=True), nullable=True),
        sa.Column("preview_token", sa.String(length=64), nullable=True),
        sa.Column("required_access_level_ids", JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"], ["cms_category.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["layout_id"], ["cms_layout.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["style_id"], ["cms_style.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_cms_page_slug", "cms_page", ["slug"], unique=True)
    op.create_index("ix_cms_page_category_id", "cms_page", ["category_id"])
    op.create_index("ix_cms_page_layout_id", "cms_page", ["layout_id"])
    op.create_index("ix_cms_page_style_id", "cms_page", ["style_id"])
    op.create_index("ix_cms_page_preview_token", "cms_page", ["preview_token"])

    op.create_table(
        "cms_page_widget",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("page_id", UUID(as_uuid=True), nullable=False),
        sa.Column("widget_id", UUID(as_uuid=True), nullable=False),
        sa.Column("area_name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("required_access_level_ids", JSON(), nullable=False),
        sa.ForeignKeyConstraint(["page_id"], ["cms_page.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["widget_id"], ["cms_widget.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_cms_page_widget_page_id", "cms_page_widget", ["page_id"])
    op.create_index("ix_cms_page_widget_widget_id", "cms_page_widget", ["widget_id"])

    op.create_table(
        "cms_page_content_block",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("page_id", UUID(as_uuid=True), nullable=False),
        sa.Column("area_name", sa.String(length=100), nullable=False),
        sa.Column("content_json", JSON(), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("source_css", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["page_id"], ["cms_page.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("page_id", "area_name", name="uq_page_content_block_area"),
    )
    op.create_index(
        "ix_cms_page_content_block_page_id", "cms_page_content_block", ["page_id"]
    )
