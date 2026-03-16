"""CMS templates: add cms_layout, cms_widget, cms_menu_item, cms_style,
cms_layout_widget tables; extend cms_page with layout_id, style_id,
use_theme_switcher_styles columns.

Revision ID: 20260305_cms_templates
Revises: 20260305_cms_widen_slug
Create Date: 2026-03-05 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260305_cms_templates"
down_revision: Union[str, None] = "20260305_cms_widen_slug"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── cms_style ─────────────────────────────────────────────────────────────
    op.create_table(
        "cms_style",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(128), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_css", sa.Text, nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cms_style_slug", "cms_style", ["slug"])

    # ── cms_layout ────────────────────────────────────────────────────────────
    op.create_table(
        "cms_layout",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(128), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("areas", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cms_layout_slug", "cms_layout", ["slug"])

    # ── cms_widget ────────────────────────────────────────────────────────────
    op.create_table(
        "cms_widget",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(128), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("widget_type", sa.String(32), nullable=False),
        sa.Column("content_json", sa.JSON, nullable=True),
        sa.Column("content_html", sa.Text, nullable=True),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cms_widget_slug", "cms_widget", ["slug"])

    # ── cms_menu_item ─────────────────────────────────────────────────────────
    op.create_table(
        "cms_menu_item",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("widget_id", UUID(as_uuid=True),
                  sa.ForeignKey("cms_widget.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True),
                  sa.ForeignKey("cms_menu_item.id", ondelete="CASCADE"), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("url", sa.String(512), nullable=True),
        sa.Column("page_slug", sa.String(512), nullable=True),
        sa.Column("target", sa.String(16), nullable=False, server_default="_self"),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cms_menu_item_widget_id", "cms_menu_item", ["widget_id"])
    op.create_index("ix_cms_menu_item_parent_id", "cms_menu_item", ["parent_id"])

    # ── cms_layout_widget ─────────────────────────────────────────────────────
    op.create_table(
        "cms_layout_widget",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("layout_id", UUID(as_uuid=True),
                  sa.ForeignKey("cms_layout.id", ondelete="CASCADE"), nullable=False),
        sa.Column("widget_id", UUID(as_uuid=True),
                  sa.ForeignKey("cms_widget.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("area_name", sa.String(64), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cms_layout_widget_layout_id", "cms_layout_widget", ["layout_id"])
    op.create_index("ix_cms_layout_widget_widget_id", "cms_layout_widget", ["widget_id"])

    # ── cms_page extensions ───────────────────────────────────────────────────
    op.add_column("cms_page", sa.Column(
        "layout_id", UUID(as_uuid=True),
        sa.ForeignKey("cms_layout.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("cms_page", sa.Column(
        "style_id", UUID(as_uuid=True),
        sa.ForeignKey("cms_style.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("cms_page", sa.Column(
        "use_theme_switcher_styles", sa.Boolean, nullable=False, server_default="true",
    ))
    op.create_index("ix_cms_page_layout_id", "cms_page", ["layout_id"])
    op.create_index("ix_cms_page_style_id", "cms_page", ["style_id"])


def downgrade() -> None:
    op.drop_index("ix_cms_page_style_id", "cms_page")
    op.drop_index("ix_cms_page_layout_id", "cms_page")
    op.drop_column("cms_page", "use_theme_switcher_styles")
    op.drop_column("cms_page", "style_id")
    op.drop_column("cms_page", "layout_id")

    op.drop_table("cms_layout_widget")
    op.drop_table("cms_menu_item")
    op.drop_table("cms_widget")
    op.drop_table("cms_layout")
    op.drop_table("cms_style")
