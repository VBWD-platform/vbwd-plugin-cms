"""Integration: CMS entity exchangers (real PG) — round-trip by natural key.

Each CMS exchanger round-trips (export → wipe → import → equal) by ``slug``:

* ``cms_posts`` round-trip includes the S55 ``content_blocks`` +
  ``page_assignments``.
* ``cms_images`` round-trip carries the binary (base64 in the JSON envelope and
  inside a ZIP bundle's per-entity file), reusing the gallery file storage.
* registration: after ``CmsPlugin.on_enable`` the CMS exchangers appear in
  ``data_exchange_registry`` (the live boot path).

Data is seeded through services / repositories (no raw SQL); the shared ``db``
fixture creates + drops the test DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY (delegates to the existing services); Liskov; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import io
import uuid
import zipfile

import pytest

from vbwd.services.data_exchange.envelope import (
    BundleEntry,
    build_bundle,
    build_envelope,
    read_bundle,
)
from vbwd.services.data_exchange.port import ExportSelector
from plugins.cms.src.models.cms_image import CmsImage
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_style import CmsStyle
from plugins.cms.src.models.cms_widget import CmsWidget
from plugins.cms.src.repositories.cms_image_repository import CmsImageRepository
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.cms_post_content_block_repository import (
    CmsPostContentBlockRepository,
)
from plugins.cms.src.repositories.cms_post_widget_repository import (
    CmsPostWidgetRepository,
)
from plugins.cms.src.repositories.cms_menu_item_repository import (
    CmsMenuItemRepository,
)
from plugins.cms.src.repositories.cms_layout_widget_repository import (
    CmsLayoutWidgetRepository,
)
from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.data_exchange.cms_exchangers import build_cms_exchangers
from vbwd.interfaces.file_storage import InMemoryFileStorage
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.repositories.post_term_repository import PostTermRepository


@pytest.fixture(autouse=True)
def _registry():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()
    term_type_registry.clear_term_types()


def _exchangers(session, storage=None):
    storage = storage or InMemoryFileStorage()
    return {
        exchanger.entity_key: exchanger
        for exchanger in build_cms_exchangers(session, file_storage=storage)
    }


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        layout_repo=CmsLayoutRepository(db.session),
        style_repo=CmsStyleRepository(db.session),
        content_block_repo=CmsPostContentBlockRepository(db.session),
    )


class TestPostsRoundTrip:
    def test_round_trip_includes_content_blocks_and_page_assignments(self, db):
        slug = f"home-{uuid.uuid4().hex[:8]}"
        widget = CmsWidget(slug=f"w-{slug}", name="W", widget_type="html")
        db.session.add(widget)
        db.session.commit()

        created = _post_service(db).create_post(
            {
                "type": "page",
                "slug": slug,
                "title": "Home",
                "status": "published",
                "content_blocks": [
                    {"area_name": "sidebar", "content_html": "<p>aside</p>"}
                ],
            }
        )
        CmsPostWidgetRepository(db.session).replace_for_post(
            created["id"],
            [{"widget_id": str(widget.id), "area_name": "header", "sort_order": 0}],
        )

        exchanger = _exchangers(db.session)["cms_posts"]
        before = exchanger.export(ExportSelector(all=True), include_pii=False).rows
        item = next(row for row in before if row["slug"] == slug)
        assert any(b["area_name"] == "sidebar" for b in item["content_blocks"])
        assert item["page_assignments"][0]["widget_slug"] == f"w-{slug}"

        # Wipe the post (and its area children cascade) then re-import.
        PostRepository(db.session).delete(created["id"])
        db.session.commit()
        assert PostRepository(db.session).find_by_type_and_slug("page", slug) is None

        payload = build_envelope("cms_posts", before, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created >= 1

        reimported = PostRepository(db.session).find_by_type_and_slug("page", slug)
        assert reimported is not None
        blocks = CmsPostContentBlockRepository(db.session).find_by_post(
            str(reimported.id)
        )
        assert [b.area_name for b in blocks] == ["sidebar"]
        assignments = CmsPostWidgetRepository(db.session).find_by_post(
            str(reimported.id)
        )
        assert len(assignments) == 1
        assert str(assignments[0].widget_id) == str(widget.id)


class TestTermsRoundTrip:
    def test_round_trip_by_slug(self, db):
        slug = f"news-{uuid.uuid4().hex[:8]}"
        TermRepository(db.session).save(
            _term("category", slug, "News"),
        )
        exchanger = _exchangers(db.session)["cms_terms"]
        before = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert before and before[0]["slug"] == slug

        TermRepository(db.session).bulk_delete(
            [str(TermRepository(db.session).find_by_type_and_slug("category", slug).id)]
        )
        db.session.commit()

        payload = build_envelope("cms_terms", before, instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)
        assert (
            TermRepository(db.session).find_by_type_and_slug("category", slug)
            is not None
        )


class TestModelExchangersRoundTrip:
    def test_layout_round_trip(self, db):
        slug = f"lay-{uuid.uuid4().hex[:8]}"
        CmsLayoutRepository(db.session).save(
            CmsLayout(slug=slug, name="Lay", areas=[{"name": "content"}])
        )
        self._round_trip(db, "cms_layouts", slug, CmsLayout, "name")

    def test_layout_head_html_round_trip(self, db):
        slug = f"lay-head-{uuid.uuid4().hex[:8]}"
        CmsLayoutRepository(db.session).save(
            CmsLayout(
                slug=slug,
                name="Lay Head",
                areas=[{"name": "content"}],
                head_html="<script>window.tracked=1;</script><meta name='x'>",
            )
        )
        self._round_trip(db, "cms_layouts", slug, CmsLayout, "head_html")

    def test_style_round_trip(self, db):
        slug = f"sty-{uuid.uuid4().hex[:8]}"
        CmsStyleRepository(db.session).save(
            CmsStyle(slug=slug, name="Sty", source_css=".x{color:red}")
        )
        self._round_trip(db, "cms_styles", slug, CmsStyle, "source_css")

    def test_widget_round_trip(self, db):
        slug = f"wid-{uuid.uuid4().hex[:8]}"
        CmsWidgetRepository(db.session).save(
            CmsWidget(slug=slug, name="Wid", widget_type="html")
        )
        self._round_trip(db, "cms_widgets", slug, CmsWidget, "widget_type")

    def test_widget_export_omits_is_global(self, db):
        # The is_global feature was removed; the exchanger must not export it.
        slug = f"gw-{uuid.uuid4().hex[:8]}"
        CmsWidgetRepository(db.session).save(
            CmsWidget(slug=slug, name="Plain", widget_type="html")
        )
        exchanger = _exchangers(db.session)["cms_widgets"]
        before = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert before and "is_global" not in before[0]

    def test_importing_new_default_style_demotes_current_default(self, db):
        # Singleton-default invariant: ix_cms_style_default_singleton allows at
        # most one is_default=True row. Importing a DIFFERENT-slug default while
        # one already exists must demote the incumbent, not raise UniqueViolation.
        incumbent = f"sty-old-{uuid.uuid4().hex[:8]}"
        incoming = f"sty-new-{uuid.uuid4().hex[:8]}"
        CmsStyleRepository(db.session).save(
            CmsStyle(slug=incumbent, name="Old", source_css=".a{}", is_default=True)
        )
        db.session.commit()

        exchanger = _exchangers(db.session)["cms_styles"]
        payload = build_envelope(
            "cms_styles",
            [
                {
                    "slug": incoming,
                    "name": "New",
                    "source_css": ".b{}",
                    "is_default": True,
                }
            ],
            instance="test",
        )
        exchanger.import_(payload, mode="upsert", dry_run=False)

        defaults = (
            db.session.query(CmsStyle).filter(CmsStyle.is_default.is_(True)).all()
        )
        assert [s.slug for s in defaults] == [incoming]

    def test_importing_new_default_layout_demotes_current_default(self, db):
        incumbent = f"lay-old-{uuid.uuid4().hex[:8]}"
        incoming = f"lay-new-{uuid.uuid4().hex[:8]}"
        CmsLayoutRepository(db.session).save(
            CmsLayout(
                slug=incumbent,
                name="Old",
                areas=[{"name": "content"}],
                is_default=True,
            )
        )
        db.session.commit()

        exchanger = _exchangers(db.session)["cms_layouts"]
        payload = build_envelope(
            "cms_layouts",
            [
                {
                    "slug": incoming,
                    "name": "New",
                    "areas": [{"name": "content"}],
                    "is_default": True,
                }
            ],
            instance="test",
        )
        exchanger.import_(payload, mode="upsert", dry_run=False)

        defaults = (
            db.session.query(CmsLayout).filter(CmsLayout.is_default.is_(True)).all()
        )
        assert [layout.slug for layout in defaults] == [incoming]

    def _round_trip(self, db, key, slug, model_class, value_field):
        exchanger = _exchangers(db.session)[key]
        before = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert before and before[0]["slug"] == slug
        expected_value = before[0][value_field]

        db.session.query(model_class).filter(model_class.slug == slug).delete()
        db.session.commit()

        payload = build_envelope(key, before, instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)
        rebuilt = db.session.query(model_class).filter(model_class.slug == slug).first()
        assert rebuilt is not None
        assert getattr(rebuilt, value_field) == expected_value


class TestLayoutsWidgetPlacementsRoundTrip:
    """The ``cms_layouts`` exchanger carries the ``cms_layout_widget`` PLACEMENTS
    (widget→area mapping) by widget slug, so an import restores which widgets
    sit in which areas — no manual ``PUT /admin/cms/layouts/<id>/widgets``."""

    def _seed_layout_with_placements(self, db, suffix):
        widget_a = CmsWidget(slug=f"wa-{suffix}", name="Nav", widget_type="html")
        widget_b = CmsWidget(slug=f"wb-{suffix}", name="Foot", widget_type="html")
        db.session.add(widget_a)
        db.session.add(widget_b)
        db.session.commit()
        layout_slug = f"lay-{suffix}"
        CmsLayoutRepository(db.session).save(
            CmsLayout(
                slug=layout_slug,
                name="Lay",
                areas=[{"name": "header"}, {"name": "footer"}],
            )
        )
        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        CmsLayoutWidgetRepository(db.session).replace_for_layout(
            str(layout.id),
            [
                {
                    "widget_id": str(widget_a.id),
                    "area_name": "header",
                    "sort_order": 0,
                },
                {
                    "widget_id": str(widget_b.id),
                    "area_name": "footer",
                    "sort_order": 1,
                },
            ],
        )
        return layout_slug, widget_a, widget_b

    def _export_layout_row(self, db, layout_slug):
        exchanger = _exchangers(db.session)["cms_layouts"]
        rows = exchanger.export(
            ExportSelector(ids=[layout_slug]), include_pii=False
        ).rows
        assert rows and rows[0]["slug"] == layout_slug
        return rows[0]

    def test_export_emits_widget_assignments_by_slug_without_widget_id(self, db):
        suffix = uuid.uuid4().hex[:8]
        layout_slug, widget_a, widget_b = self._seed_layout_with_placements(db, suffix)
        row = self._export_layout_row(db, layout_slug)

        assignments = row["widget_assignments"]
        by_area = {item["area_name"]: item for item in assignments}
        assert set(by_area) == {"header", "footer"}
        assert by_area["header"]["widget_slug"] == widget_a.slug
        assert by_area["header"]["sort_order"] == 0
        assert by_area["footer"]["widget_slug"] == widget_b.slug
        assert by_area["footer"]["sort_order"] == 1
        for assignment in assignments:
            assert "widget_id" not in assignment
            assert "required_access_level_ids" not in assignment

    def test_round_trip_recreates_placements_resolved_by_slug(self, db):
        suffix = uuid.uuid4().hex[:8]
        layout_slug, widget_a, widget_b = self._seed_layout_with_placements(db, suffix)
        row = self._export_layout_row(db, layout_slug)

        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        CmsLayoutWidgetRepository(db.session).delete_by_layout(str(layout.id))
        db.session.query(CmsLayout).filter(CmsLayout.slug == layout_slug).delete()
        db.session.commit()
        assert CmsLayoutRepository(db.session).find_by_slug(layout_slug) is None

        exchanger = _exchangers(db.session)["cms_layouts"]
        payload = build_envelope("cms_layouts", [row], instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1 and not result.errors

        rebuilt = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        assert rebuilt is not None
        placements = CmsLayoutWidgetRepository(db.session).find_by_layout(
            str(rebuilt.id)
        )
        by_area = {p.area_name: p for p in placements}
        assert set(by_area) == {"header", "footer"}
        assert str(by_area["header"].widget_id) == str(widget_a.id)
        assert str(by_area["footer"].widget_id) == str(widget_b.id)
        assert by_area["footer"].sort_order == 1

    def test_reimport_is_idempotent_no_duplicate_placements(self, db):
        suffix = uuid.uuid4().hex[:8]
        layout_slug, _widget_a, _widget_b = self._seed_layout_with_placements(
            db, suffix
        )
        row = self._export_layout_row(db, layout_slug)

        exchanger = _exchangers(db.session)["cms_layouts"]
        payload = build_envelope("cms_layouts", [row], instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)
        exchanger.import_(payload, mode="upsert", dry_run=False)

        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        placements = CmsLayoutWidgetRepository(db.session).find_by_layout(
            str(layout.id)
        )
        assert len(placements) == 2, "re-import must replace-set, not duplicate"

    def test_unknown_widget_slug_is_reported_layout_still_imported(self, db):
        suffix = uuid.uuid4().hex[:8]
        layout_slug, widget_a, _widget_b = self._seed_layout_with_placements(db, suffix)
        row = self._export_layout_row(db, layout_slug)
        # Point one placement at a widget that does not exist on the target.
        for assignment in row["widget_assignments"]:
            if assignment["area_name"] == "footer":
                assignment["widget_slug"] = f"ghost-{suffix}"

        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        CmsLayoutWidgetRepository(db.session).delete_by_layout(str(layout.id))
        db.session.query(CmsLayout).filter(CmsLayout.slug == layout_slug).delete()
        db.session.commit()

        exchanger = _exchangers(db.session)["cms_layouts"]
        payload = build_envelope("cms_layouts", [row], instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)

        # Layout imported, the known placement applied, the ghost reported.
        assert result.created == 1
        assert any("ghost" in error["reason"] for error in result.errors)
        rebuilt = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        assert rebuilt is not None
        placements = CmsLayoutWidgetRepository(db.session).find_by_layout(
            str(rebuilt.id)
        )
        assert len(placements) == 1
        assert str(placements[0].widget_id) == str(widget_a.id)

    def test_dry_run_writes_no_placements(self, db):
        suffix = uuid.uuid4().hex[:8]
        layout_slug, _widget_a, _widget_b = self._seed_layout_with_placements(
            db, suffix
        )
        row = self._export_layout_row(db, layout_slug)

        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        CmsLayoutWidgetRepository(db.session).delete_by_layout(str(layout.id))
        db.session.commit()
        assert (
            CmsLayoutWidgetRepository(db.session).find_by_layout(str(layout.id)) == []
        )

        exchanger = _exchangers(db.session)["cms_layouts"]
        payload = build_envelope("cms_layouts", [row], instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=True)

        layout = CmsLayoutRepository(db.session).find_by_slug(layout_slug)
        assert (
            CmsLayoutWidgetRepository(db.session).find_by_layout(str(layout.id)) == []
        )


class TestWidgetsMenuItemsRoundTrip:
    """S68 Bug A — the unified ``cms_widgets`` exchanger must carry the
    ``cms_menu_item`` tree of a menu widget (export AND import), at parity with
    the bespoke ``CmsWidgetService.export_widget`` / ``import_widget`` path."""

    def _seed_menu_widget(self, db, slug):
        CmsWidgetRepository(db.session).save(
            CmsWidget(slug=slug, name="Main Menu", widget_type="menu")
        )
        widget = CmsWidgetRepository(db.session).find_by_slug(slug)
        CmsMenuItemRepository(db.session).replace_tree(
            str(widget.id),
            [
                {
                    "id": "placeholder-software",
                    "label": "Software",
                    "url": "/category",
                    "target": "_self",
                    "sort_order": 0,
                },
                {
                    "id": "placeholder-home",
                    "parent_id": "placeholder-software",
                    "label": "Home",
                    "page_slug": "home1",
                    "target": "_blank",
                    "sort_order": 1,
                },
                {
                    "id": "placeholder-about",
                    "label": "About",
                    "page_slug": "about",
                    "target": "_self",
                    "sort_order": 2,
                },
            ],
        )
        return widget

    def _exported_row(self, db, slug):
        exchanger = _exchangers(db.session)["cms_widgets"]
        rows = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert rows and rows[0]["slug"] == slug
        return rows[0]

    def _items_by_label(self, db, widget_id):
        items = CmsMenuItemRepository(db.session).find_tree_by_widget(str(widget_id))
        return {item.label: item for item in items}

    def test_menu_widget_export_includes_menu_items_tree(self, db):
        slug = f"menu-{uuid.uuid4().hex[:8]}"
        self._seed_menu_widget(db, slug)
        row = self._exported_row(db, slug)

        menu_items = row.get("menu_items")
        assert menu_items is not None, "menu widget export must carry menu_items"
        by_label = {item["label"]: item for item in menu_items}
        assert set(by_label) == {"Software", "Home", "About"}
        assert by_label["Software"]["url"] == "/category"
        assert by_label["Home"]["page_slug"] == "home1"
        assert by_label["Home"]["target"] == "_blank"
        assert by_label["About"]["sort_order"] == 2
        # ids + parent ids must travel so the import two-pass remap works.
        assert by_label["Software"]["id"]
        assert by_label["Home"]["parent_id"] == by_label["Software"]["id"]

    def test_non_menu_widget_export_has_no_menu_items_key(self, db):
        slug = f"html-{uuid.uuid4().hex[:8]}"
        CmsWidgetRepository(db.session).save(
            CmsWidget(
                slug=slug,
                name="HTML Block",
                widget_type="html",
                content_json={"content": "PHA+aGk8L3A+"},
                config={"foo": "bar"},
            )
        )
        row = self._exported_row(db, slug)
        assert "menu_items" not in row
        assert row["content_json"] == {"content": "PHA+aGk8L3A+"}
        assert row["config"] == {"foo": "bar"}

    def test_round_trip_reconstructs_menu_tree(self, db):
        slug = f"menu-{uuid.uuid4().hex[:8]}"
        self._seed_menu_widget(db, slug)
        row = self._exported_row(db, slug)

        # Wipe the widget (menu items cascade away at the DB level).
        db.session.query(CmsWidget).filter(CmsWidget.slug == slug).delete()
        db.session.commit()

        exchanger = _exchangers(db.session)["cms_widgets"]
        payload = build_envelope("cms_widgets", [row], instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1 and not result.errors

        rebuilt = CmsWidgetRepository(db.session).find_by_slug(slug)
        assert rebuilt is not None
        by_label = self._items_by_label(db, rebuilt.id)
        assert set(by_label) == {"Software", "Home", "About"}
        assert str(by_label["Home"].parent_id) == str(by_label["Software"].id)
        assert by_label["Software"].parent_id is None
        assert by_label["Software"].url == "/category"
        assert by_label["Home"].page_slug == "home1"
        assert by_label["Home"].target == "_blank"
        sort_orders = [
            by_label[label].sort_order for label in ("Software", "Home", "About")
        ]
        assert sort_orders == [0, 1, 2]

    def test_reimport_is_idempotent(self, db):
        slug = f"menu-{uuid.uuid4().hex[:8]}"
        widget = self._seed_menu_widget(db, slug)
        row = self._exported_row(db, slug)

        exchanger = _exchangers(db.session)["cms_widgets"]
        payload = build_envelope("cms_widgets", [row], instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)
        exchanger.import_(payload, mode="upsert", dry_run=False)

        items = CmsMenuItemRepository(db.session).find_tree_by_widget(str(widget.id))
        assert len(items) == 3, "re-import must not duplicate menu rows"

    def test_import_without_menu_items_is_clean(self, db):
        slug = f"menu-{uuid.uuid4().hex[:8]}"
        row = {
            "slug": slug,
            "name": "Bare Menu",
            "widget_type": "menu",
            "content_json": None,
            "source_css": None,
            "config": None,
            "sort_order": 0,
            "is_active": True,
        }
        exchanger = _exchangers(db.session)["cms_widgets"]
        payload = build_envelope("cms_widgets", [row], instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1 and not result.errors

        widget = CmsWidgetRepository(db.session).find_by_slug(slug)
        assert widget is not None
        assert (
            CmsMenuItemRepository(db.session).find_tree_by_widget(str(widget.id)) == []
        )


class TestImagesRoundTrip:
    def test_export_selected_by_primary_id(self, db):
        """fe-admin "Export selected" sends the image's primary id (UUID)."""
        slug = f"img-{uuid.uuid4().hex[:8]}"
        file_path = f"images/{slug}.png"
        storage = InMemoryFileStorage()
        storage.save(b"x", file_path)
        CmsImageRepository(db.session).save(
            CmsImage(slug=slug, file_path=file_path, url_path=f"/uploads/{file_path}")
        )
        image_id = CmsImageRepository(db.session).find_by_slug(slug).id
        exchanger = _exchangers(db.session, storage)["cms_images"]
        rows = exchanger.export(
            ExportSelector(ids=[str(image_id)]), include_pii=False
        ).rows
        assert [r["slug"] for r in rows] == [slug]

    def test_json_round_trip_carries_binary(self, db):
        slug = f"img-{uuid.uuid4().hex[:8]}"
        file_path = f"images/{slug}.png"
        raw = b"\x89PNG\r\n\x1a\nfake-bytes"
        storage = InMemoryFileStorage()
        storage.save(raw, file_path)
        CmsImageRepository(db.session).save(
            CmsImage(slug=slug, file_path=file_path, url_path=f"/uploads/{file_path}")
        )

        exchanger = _exchangers(db.session, storage)["cms_images"]
        before = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert before and before[0]["data"] is not None

        # Wipe the row + binary, then re-import → row and bytes return.
        CmsImageRepository(db.session).bulk_delete(
            [str(CmsImageRepository(db.session).find_by_slug(slug).id)]
        )
        db.session.commit()
        storage.delete(file_path)

        payload = build_envelope("cms_images", before, instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)
        rebuilt = CmsImageRepository(db.session).find_by_slug(slug)
        assert rebuilt is not None
        assert storage.read(file_path) == raw

    def test_export_zip_emits_real_archive_with_asset_file(self, db):
        """The route's zip path (``export_zip`` → ``build_envelope`` →
        ``build_bundle``) yields a VALID zip whose ``assets/`` carries the raw
        image bytes (not base64) — the bug was that no zip branch existed and a
        JSON envelope was saved as ``.zip``."""
        slug = f"realzip-{uuid.uuid4().hex[:8]}"
        file_path = f"images/{slug}.png"
        raw = b"\x89PNG\r\n\x1a\nreal-archive-bytes"
        storage = InMemoryFileStorage()
        storage.save(raw, file_path)
        CmsImageRepository(db.session).save(
            CmsImage(slug=slug, file_path=file_path, url_path=f"/uploads/{file_path}")
        )

        exchanger = _exchangers(db.session, storage)["cms_images"]
        zip_export = exchanger.export_zip(ExportSelector(ids=[slug]), include_pii=False)
        envelope = build_envelope("cms_images", zip_export.rows, instance="test")
        bundle = build_bundle(
            [BundleEntry("cms_images", "json", envelope)],
            instance="test",
            assets=zip_export.assets,
        )

        # The bytes are a genuine, openable zip — the regression assertion.
        archive = zipfile.ZipFile(io.BytesIO(bundle))
        names = archive.namelist()
        assert "manifest.json" in names
        assert "cms_images.json" in names
        asset_names = [name for name in names if name.startswith("assets/")]
        assert asset_names, "the bundle must contain a real image file under assets/"
        assert archive.read(asset_names[0]) == raw
        # The entity file references the asset by filename, not base64.
        rows = exchanger and zip_export.rows
        assert rows[0]["asset_file"] and "data" not in rows[0]

    def test_zip_export_round_trips_through_route_path(self, db):
        """Re-importing the asset-backed bundle (``read_bundle`` →
        ``attach_assets`` → ``import_``) recreates the row AND the binary."""
        slug = f"rt-{uuid.uuid4().hex[:8]}"
        file_path = f"images/{slug}.png"
        raw = b"round-trip-image-bytes"
        storage = InMemoryFileStorage()
        storage.save(raw, file_path)
        CmsImageRepository(db.session).save(
            CmsImage(slug=slug, file_path=file_path, url_path=f"/uploads/{file_path}")
        )

        exchanger = _exchangers(db.session, storage)["cms_images"]
        zip_export = exchanger.export_zip(ExportSelector(ids=[slug]), include_pii=False)
        envelope = build_envelope("cms_images", zip_export.rows, instance="test")
        bundle = build_bundle(
            [BundleEntry("cms_images", "json", envelope)],
            instance="test",
            assets=zip_export.assets,
        )

        CmsImageRepository(db.session).bulk_delete(
            [str(CmsImageRepository(db.session).find_by_slug(slug).id)]
        )
        db.session.commit()
        storage.delete(file_path)

        _manifest, entries, assets = read_bundle(bundle)
        payload = exchanger.attach_assets(entries["cms_images"], assets)
        exchanger.import_(payload, mode="upsert", dry_run=False)
        assert CmsImageRepository(db.session).find_by_slug(slug) is not None
        assert storage.read(file_path) == raw

    def test_zip_bundle_round_trip(self, db):
        slug = f"zimg-{uuid.uuid4().hex[:8]}"
        file_path = f"images/{slug}.png"
        raw = b"zip-image-bytes"
        storage = InMemoryFileStorage()
        storage.save(raw, file_path)
        CmsImageRepository(db.session).save(
            CmsImage(slug=slug, file_path=file_path, url_path=f"/uploads/{file_path}")
        )

        exchanger = _exchangers(db.session, storage)["cms_images"]
        rows = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        envelope = build_envelope("cms_images", rows, instance="test")
        bundle = build_bundle(
            [BundleEntry("cms_images", "json", envelope)], instance="test"
        )

        CmsImageRepository(db.session).bulk_delete(
            [str(CmsImageRepository(db.session).find_by_slug(slug).id)]
        )
        db.session.commit()
        storage.delete(file_path)

        _manifest, entries, _assets = read_bundle(bundle)
        exchanger.import_(entries["cms_images"], mode="upsert", dry_run=False)
        assert CmsImageRepository(db.session).find_by_slug(slug) is not None
        assert storage.read(file_path) == raw


class TestRegistration:
    def test_on_enable_registers_cms_exchangers(self, db):
        from vbwd.services.data_exchange.registry import data_exchange_registry
        from plugins.cms import CmsPlugin

        plugin = CmsPlugin()
        plugin.initialize({})
        plugin._register_data_exchangers()
        keys = {exchanger.entity_key for exchanger in data_exchange_registry.all()}
        assert {
            "cms_posts",
            "cms_terms",
            "cms_layouts",
            "cms_styles",
            "cms_widgets",
            "cms_images",
        } <= keys


def _term(term_type, slug, name):
    from plugins.cms.src.models.cms_term import CmsTerm

    term = CmsTerm()
    term.term_type = term_type
    term.slug = slug
    term.name = name
    return term
