"""TDD unit tests for CmsImportExportService.

Run:
    docker compose run --rm test python -m pytest \
        plugins/cms/tests/unit/services/test_cms_import_export_service.py -v
"""
import io
import json
import zipfile
from unittest.mock import MagicMock
from uuid import uuid4
import datetime

from plugins.cms.src.services.cms_import_export_service import CmsImportExportService
from plugins.cms.src.services.file_storage import InMemoryFileStorage


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_widget(slug="w1", name="Widget 1", wtype="html"):
    from plugins.cms.src.models.cms_widget import CmsWidget

    w = CmsWidget()
    w.id = uuid4()
    w.slug = slug
    w.name = name
    w.widget_type = wtype
    w.content_json = {}
    w.source_css = None
    w.config = None
    w.sort_order = 0
    w.is_active = True
    w.created_at = w.updated_at = datetime.datetime.utcnow()
    return w


def _make_category(slug="cat1", name="Cat 1"):
    from plugins.cms.src.models.cms_category import CmsCategory

    c = CmsCategory()
    c.id = uuid4()
    c.slug = slug
    c.name = name
    c.parent_id = None
    c.sort_order = 0
    c.created_at = c.updated_at = datetime.datetime.utcnow()
    return c


def _make_style(slug="sty1", name="Style 1"):
    from plugins.cms.src.models.cms_style import CmsStyle

    s = CmsStyle()
    s.id = uuid4()
    s.slug = slug
    s.name = name
    s.source_css = ".a{}"
    s.sort_order = 0
    s.is_active = True
    s.created_at = s.updated_at = datetime.datetime.utcnow()
    return s


def _make_layout(slug="lay1", name="Layout 1"):
    from plugins.cms.src.models.cms_layout import CmsLayout

    lay = CmsLayout()
    lay.id = uuid4()
    lay.slug = slug
    lay.name = name
    lay.description = ""
    lay.areas = []
    lay.sort_order = 0
    lay.is_active = True
    lay.created_at = lay.updated_at = datetime.datetime.utcnow()
    return lay


def _make_page(slug="pg1", name="Page 1"):
    from plugins.cms.src.models.cms_page import CmsPage

    p = CmsPage()
    p.id = uuid4()
    p.slug = slug
    p.name = name
    p.language = "en"
    p.content_json = {}
    p.content_html = None
    p.source_css = None
    p.category_id = None
    p.layout_id = None
    p.style_id = None
    p.is_published = False
    p.sort_order = 0
    p.meta_title = None
    p.meta_description = None
    p.meta_keywords = None
    p.og_title = None
    p.og_description = None
    p.og_image_url = None
    p.canonical_url = None
    p.robots = "index,follow"
    p.schema_json = None
    p.created_at = p.updated_at = datetime.datetime.utcnow()
    return p


def _make_routing_rule(name="Rule 1"):
    from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule

    r = CmsRoutingRule()
    r.id = uuid4()
    r.name = name
    r.is_active = True
    r.priority = 0
    r.match_type = "default"
    r.match_value = None
    r.target_slug = "home"
    r.redirect_code = 302
    r.is_rewrite = False
    r.layer = "middleware"
    r.created_at = r.updated_at = datetime.datetime.utcnow()
    return r


def _make_image(slug="img1"):
    from plugins.cms.src.models.cms_image import CmsImage

    img = CmsImage()
    img.id = uuid4()
    img.slug = slug
    img.caption = "cap"
    img.file_path = f"{slug}.jpg"
    img.url_path = f"/uploads/{slug}.jpg"
    img.mime_type = "image/jpeg"
    img.file_size_bytes = 100
    img.width_px = 800
    img.height_px = 600
    img.alt_text = "alt"
    img.created_at = img.updated_at = datetime.datetime.utcnow()
    return img


def _paginated(items):
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "per_page": 100000,
        "pages": 1,
    }


def _make_svc(
    categories=None,
    styles=None,
    widgets=None,
    layouts=None,
    pages=None,
    routing_rules=None,
    images=None,
    lw_assignments=None,
    storage=None,
):
    cat_repo = MagicMock()
    cat_repo.find_all.return_value = categories or []
    cat_repo.find_by_slug.return_value = None
    cat_repo.find_by_id.return_value = None
    _wire_slug_store(cat_repo, categories or [])

    style_repo = MagicMock()
    style_repo.find_all.return_value = _paginated(styles or [])
    _wire_slug_store(style_repo, styles or [])

    widget_repo = MagicMock()
    widget_repo.find_all.return_value = _paginated(widgets or [])
    _wire_slug_store(widget_repo, widgets or [])

    layout_repo = MagicMock()
    layout_repo.find_all.return_value = _paginated(layouts or [])
    _wire_slug_store(layout_repo, layouts or [])

    page_repo = MagicMock()
    page_repo.find_all.return_value = _paginated(pages or [])
    _wire_slug_store(page_repo, pages or [])

    routing_repo = MagicMock()
    routing_repo.find_all.return_value = routing_rules or []
    routing_repo.find_by_id.return_value = None

    image_repo = MagicMock()
    image_repo.find_all.return_value = _paginated(images or [])
    _wire_slug_store(image_repo, images or [])

    lw_repo = MagicMock()
    lw_repo.find_by_layout.return_value = lw_assignments or []

    fs = storage or InMemoryFileStorage()

    return (
        CmsImportExportService(
            cat_repo,
            style_repo,
            widget_repo,
            layout_repo,
            page_repo,
            routing_repo,
            image_repo,
            lw_repo,
            fs,
        ),
        cat_repo,
        style_repo,
        widget_repo,
        layout_repo,
        page_repo,
        routing_repo,
        image_repo,
        lw_repo,
    )


def _wire_slug_store(repo, items):
    store = {obj.slug: obj for obj in items}
    id_store = {str(obj.id): obj for obj in items}
    repo.find_by_slug.side_effect = lambda s: store.get(s)
    repo.find_by_id.side_effect = lambda i: id_store.get(str(i))

    def _save(obj):
        store[obj.slug] = obj
        id_store[str(obj.id)] = obj
        return obj

    repo.save.side_effect = _save


def _parse_zip(data: bytes) -> dict:
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                result[name] = json.loads(zf.read(name))
            else:
                result[name] = zf.read(name)
    return result


def _make_zip(**section_dicts) -> bytes:
    sections = list(section_dicts.keys())
    manifest = {
        "version": "1.0",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "sections": sections,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in section_dicts.items():
            zf.writestr(f"{name}.json", json.dumps(data))
    buf.seek(0)
    return buf.read()


# ── TestExportManifest ─────────────────────────────────────────────────────────


class TestExportManifest:
    def test_manifest_present_in_zip(self):
        svc, *_ = _make_svc()
        contents = _parse_zip(svc.export(["widgets"]))
        assert "manifest.json" in contents

    def test_manifest_lists_requested_sections(self):
        svc, *_ = _make_svc(widgets=[_make_widget()])
        contents = _parse_zip(svc.export(["widgets", "categories"]))
        manifest = contents["manifest.json"]
        assert set(manifest["sections"]) == {"widgets", "categories"}

    def test_manifest_all_includes_every_section(self):
        svc, *_ = _make_svc()
        contents = _parse_zip(svc.export(["all"]))
        manifest = contents["manifest.json"]
        assert "widgets" in manifest["sections"]
        assert "pages" in manifest["sections"]
        assert "categories" in manifest["sections"]

    def test_manifest_everything_includes_every_section(self):
        """Frontend sends 'everything'; must behave identically to 'all'."""
        svc, *_ = _make_svc()
        contents = _parse_zip(svc.export(["everything"]))
        manifest = contents["manifest.json"]
        from plugins.cms.src.services.cms_import_export_service import VALID_SECTIONS

        assert set(manifest["sections"]) == VALID_SECTIONS


# ── TestExportSections ─────────────────────────────────────────────────────────


class TestExportSections:
    def test_export_widgets_section_present(self):
        w = _make_widget("footer-nav")
        svc, *_ = _make_svc(widgets=[w])
        contents = _parse_zip(svc.export(["widgets"]))
        assert "widgets.json" in contents
        assert contents["widgets.json"][0]["slug"] == "footer-nav"

    def test_export_omits_unrequested_sections(self):
        svc, *_ = _make_svc(widgets=[_make_widget()])
        contents = _parse_zip(svc.export(["widgets"]))
        assert "pages.json" not in contents

    def test_export_categories_returns_list(self):
        cats = [_make_category("cat-a"), _make_category("cat-b")]
        svc, *_ = _make_svc(categories=cats)
        contents = _parse_zip(svc.export(["categories"]))
        assert len(contents["categories.json"]) == 2

    def test_export_image_includes_binary_when_stored(self):
        img = _make_image("hero")
        fs = InMemoryFileStorage()
        fs.save(b"fakepng", "hero.jpg")
        svc, *_ = _make_svc(images=[img], storage=fs)
        contents = _parse_zip(svc.export(["images"]))
        assert contents.get("images/hero.jpg") == b"fakepng"


# ── TestImportAdd ──────────────────────────────────────────────────────────────


class TestImportAdd:
    def test_import_add_inserts_new_widget(self):
        data = _make_zip(
            widgets=[
                {
                    "slug": "new-w",
                    "name": "New",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["imported"]["widgets"] == 1
        widget_repo.save.assert_called_once()

    def test_import_add_skips_existing_slug(self):
        existing = _make_widget("existing-w")
        data = _make_zip(
            widgets=[
                {
                    "slug": "existing-w",
                    "name": "X",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc(widgets=[existing])
        result = svc.import_zip(data, "add")
        assert result["imported"]["widgets"] == 0
        widget_repo.save.assert_not_called()

    def test_import_add_inserts_categories(self):
        data = _make_zip(
            categories=[{"slug": "software", "name": "Software", "sort_order": 0}]
        )
        svc, cat_repo, *_ = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["imported"]["categories"] == 1
        cat_repo.save.assert_called_once()

    def test_import_returns_no_errors_on_success(self):
        data = _make_zip(
            widgets=[
                {
                    "slug": "w-ok",
                    "name": "OK",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, *_ = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["errors"] == []


# ── TestImportIndex ────────────────────────────────────────────────────────────


class TestImportIndex:
    def test_import_index_renames_slug_on_conflict(self):
        existing = _make_widget("breadcrumbs")
        data = _make_zip(
            widgets=[
                {
                    "slug": "breadcrumbs",
                    "name": "BC",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc(widgets=[existing])
        result = svc.import_zip(data, "index")
        assert result["imported"]["widgets"] == 1
        saved_obj = widget_repo.save.call_args[0][0]
        assert saved_obj.slug == "breadcrumbs-2"

    def test_import_index_increments_to_next_free_suffix(self):
        w1 = _make_widget("nav")
        w2 = _make_widget("nav-2")
        data = _make_zip(
            widgets=[
                {
                    "slug": "nav",
                    "name": "Nav",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc(widgets=[w1, w2])
        svc.import_zip(data, "index")
        saved_obj = widget_repo.save.call_args[0][0]
        assert saved_obj.slug == "nav-3"

    def test_import_index_inserts_non_conflicting_as_is(self):
        data = _make_zip(
            widgets=[
                {
                    "slug": "unique-slug",
                    "name": "U",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc()
        svc.import_zip(data, "index")
        saved_obj = widget_repo.save.call_args[0][0]
        assert saved_obj.slug == "unique-slug"


# ── TestImportDropAll ──────────────────────────────────────────────────────────


class TestImportDropAll:
    def test_drop_all_calls_bulk_delete_for_widgets(self):
        existing = _make_widget("old-w")
        data = _make_zip(
            widgets=[
                {
                    "slug": "new-w",
                    "name": "N",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc(widgets=[existing])
        svc.import_zip(data, "drop_all")
        widget_repo.bulk_delete.assert_called_once_with([str(existing.id)])

    def test_drop_all_calls_delete_for_categories(self):
        cat = _make_category("old-cat")
        data = _make_zip(categories=[{"slug": "new-cat", "name": "N", "sort_order": 0}])
        svc, cat_repo, *_ = _make_svc(categories=[cat])
        svc.import_zip(data, "drop_all")
        cat_repo.delete.assert_called_once_with(str(cat.id))

    def test_drop_all_inserts_all_records_after_clear(self):
        existing = _make_widget("hero")
        data = _make_zip(
            widgets=[
                {
                    "slug": "hero",
                    "name": "Hero New",
                    "widget_type": "html",
                    "content_json": {},
                    "source_css": None,
                    "config": None,
                    "sort_order": 0,
                    "is_active": True,
                },
            ]
        )
        svc, _, _, widget_repo, *_ = _make_svc(widgets=[existing])
        result = svc.import_zip(data, "drop_all")
        assert result["imported"]["widgets"] == 1

    def test_drop_all_calls_delete_for_routing_rules(self):
        rule = _make_routing_rule("Rule A")
        data = _make_zip(
            routing_rules=[
                {
                    "name": "Rule B",
                    "is_active": True,
                    "priority": 0,
                    "match_type": "default",
                    "match_value": None,
                    "target_slug": "home",
                    "redirect_code": 302,
                    "is_rewrite": False,
                    "layer": "middleware",
                }
            ]
        )
        svc, *_, routing_repo, _, _ = _make_svc(routing_rules=[rule])
        svc.import_zip(data, "drop_all")
        routing_repo.delete.assert_called_once_with(str(rule.id))


# ── TestImportPages ────────────────────────────────────────────────────────────


class TestImportPages:
    def test_import_page_resolves_category_slug(self):
        cat = _make_category("software")
        data = _make_zip(
            pages=[
                {
                    "slug": "my-page",
                    "name": "My Page",
                    "language": "en",
                    "content_json": {},
                    "content_html": None,
                    "source_css": None,
                    "category_id": None,
                    "layout_id": None,
                    "style_id": None,
                    "is_published": False,
                    "sort_order": 0,
                    "meta_title": None,
                    "meta_description": None,
                    "meta_keywords": None,
                    "og_title": None,
                    "og_description": None,
                    "og_image_url": None,
                    "canonical_url": None,
                    "robots": "index,follow",
                    "schema_json": None,
                    "category_slug": "software",
                    "layout_slug": None,
                    "style_slug": None,
                }
            ]
        )
        svc, cat_repo, _, _, _, page_repo, *_ = _make_svc(categories=[cat])
        result = svc.import_zip(data, "add")
        assert result["imported"]["pages"] == 1
        saved_page = page_repo.save.call_args[0][0]
        assert saved_page.category_id == cat.id

    def test_import_page_sets_null_fk_for_missing_layout(self):
        data = _make_zip(
            pages=[
                {
                    "slug": "pg-no-layout",
                    "name": "P",
                    "language": "en",
                    "content_json": {},
                    "content_html": None,
                    "source_css": None,
                    "category_id": None,
                    "layout_id": None,
                    "style_id": None,
                    "is_published": False,
                    "sort_order": 0,
                    "meta_title": None,
                    "meta_description": None,
                    "meta_keywords": None,
                    "og_title": None,
                    "og_description": None,
                    "og_image_url": None,
                    "canonical_url": None,
                    "robots": "index,follow",
                    "schema_json": None,
                    "category_slug": None,
                    "layout_slug": "missing-layout",
                    "style_slug": None,
                }
            ]
        )
        svc, _, _, _, _, page_repo, *_ = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["imported"]["pages"] == 1
        saved_page = page_repo.save.call_args[0][0]
        assert saved_page.layout_id is None

    def test_import_page_skips_on_slug_conflict_with_add(self):
        existing = _make_page("home")
        data = _make_zip(
            pages=[
                {
                    "slug": "home",
                    "name": "Home",
                    "language": "en",
                    "content_json": {},
                    "content_html": None,
                    "source_css": None,
                    "category_id": None,
                    "layout_id": None,
                    "style_id": None,
                    "is_published": True,
                    "sort_order": 0,
                    "meta_title": None,
                    "meta_description": None,
                    "meta_keywords": None,
                    "og_title": None,
                    "og_description": None,
                    "og_image_url": None,
                    "canonical_url": None,
                    "robots": "index,follow",
                    "schema_json": None,
                    "category_slug": None,
                    "layout_slug": None,
                    "style_slug": None,
                }
            ]
        )
        svc, _, _, _, _, page_repo, *_ = _make_svc(pages=[existing])
        result = svc.import_zip(data, "add")
        assert result["imported"]["pages"] == 0
        page_repo.save.assert_not_called()


# ── TestImportLayouts ──────────────────────────────────────────────────────────


class TestImportLayouts:
    def test_import_layout_creates_widget_assignments(self):
        w = _make_widget("hero-widget")
        data = _make_zip(
            layouts=[
                {
                    "slug": "main-layout",
                    "name": "Main",
                    "description": "",
                    "areas": ["header", "main"],
                    "sort_order": 0,
                    "is_active": True,
                    "widget_assignments": [
                        {
                            "widget_slug": "hero-widget",
                            "area_name": "header",
                            "sort_order": 0,
                        },
                    ],
                }
            ]
        )
        svc, _, _, _, layout_repo, _, _, _, lw_repo = _make_svc(widgets=[w])
        result = svc.import_zip(data, "add")
        assert result["imported"]["layouts"] == 1
        lw_repo.replace_for_layout.assert_called_once()
        args = lw_repo.replace_for_layout.call_args[0]
        assert args[1][0]["widget_id"] == str(w.id)

    def test_import_layout_skips_missing_widget_slug(self):
        data = _make_zip(
            layouts=[
                {
                    "slug": "layout-x",
                    "name": "X",
                    "description": "",
                    "areas": [],
                    "sort_order": 0,
                    "is_active": True,
                    "widget_assignments": [
                        {
                            "widget_slug": "nonexistent",
                            "area_name": "main",
                            "sort_order": 0,
                        },
                    ],
                }
            ]
        )
        svc, _, _, _, layout_repo, _, _, _, lw_repo = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["imported"]["layouts"] == 1
        # replace_for_layout called but with empty assignments
        args = lw_repo.replace_for_layout.call_args
        assert args is None or args[0][1] == []


# ── TestImportImages ───────────────────────────────────────────────────────────


class TestImportImages:
    def test_import_image_saves_binary_to_storage(self):
        raw = b"\x89PNG\r\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "manifest.json",
                '{"version":"1.0","exported_at":"","sections":["images"]}',
            )
            zf.writestr(
                "images.json",
                json.dumps(
                    [
                        {
                            "slug": "logo",
                            "caption": "logo",
                            "file_path": "logo.png",
                            "url_path": "/uploads/logo.png",
                            "mime_type": "image/png",
                            "file_size_bytes": 6,
                            "width_px": 100,
                            "height_px": 50,
                            "alt_text": "logo",
                        }
                    ]
                ),
            )
            zf.writestr("images/logo.png", raw)
        buf.seek(0)

        fs = InMemoryFileStorage()
        svc, *_ = _make_svc(storage=fs)
        result = svc.import_zip(buf.read(), "add")
        assert result["imported"]["images"] == 1
        assert fs.read("logo.png") == raw

    def test_import_image_metadata_only_when_no_binary(self):
        data = _make_zip(
            images=[
                {
                    "slug": "remote-img",
                    "caption": "",
                    "file_path": "remote.jpg",
                    "url_path": "/uploads/remote.jpg",
                    "mime_type": "image/jpeg",
                    "file_size_bytes": 0,
                    "width_px": None,
                    "height_px": None,
                    "alt_text": "",
                }
            ]
        )
        svc, *_, image_repo, _ = _make_svc()
        result = svc.import_zip(data, "add")
        assert result["imported"]["images"] == 1
        image_repo.save.assert_called_once()


# ── TestImportRoutingRules ─────────────────────────────────────────────────────


class TestImportRoutingRules:
    def test_import_routing_rule_add_skips_existing_name(self):
        rule = _make_routing_rule("Default Route")
        data = _make_zip(
            routing_rules=[
                {
                    "name": "Default Route",
                    "is_active": True,
                    "priority": 0,
                    "match_type": "default",
                    "match_value": None,
                    "target_slug": "home",
                    "redirect_code": 302,
                    "is_rewrite": False,
                    "layer": "middleware",
                }
            ]
        )
        svc, *_, routing_repo, _, _ = _make_svc(routing_rules=[rule])
        result = svc.import_zip(data, "add")
        assert result["imported"]["routing_rules"] == 0
        routing_repo.save.assert_not_called()

    def test_import_routing_rule_index_renames_conflict(self):
        rule = _make_routing_rule("Default Route")
        data = _make_zip(
            routing_rules=[
                {
                    "name": "Default Route",
                    "is_active": True,
                    "priority": 0,
                    "match_type": "default",
                    "match_value": None,
                    "target_slug": "home",
                    "redirect_code": 302,
                    "is_rewrite": False,
                    "layer": "middleware",
                }
            ]
        )
        svc, *_, routing_repo, _, _ = _make_svc(routing_rules=[rule])
        result = svc.import_zip(data, "index")
        assert result["imported"]["routing_rules"] == 1
        saved = routing_repo.save.call_args[0][0]
        assert saved.name == "Default Route-2"
