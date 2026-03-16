"""CMS bulk Import/Export service.

Produces / consumes a ZIP archive containing JSON snapshots of CMS entities
plus optional image binaries.

ZIP layout:
    manifest.json          — metadata (version, exported_at, sections)
    categories.json        — List[CmsCategory.to_dict()]
    styles.json            — List[CmsStyle.to_dict()]
    widgets.json           — List[CmsWidget.to_dict()]
    layouts.json           — List[CmsLayout.to_dict() + widget_assignments]
    pages.json             — List[CmsPage.to_dict() + category/layout/style slugs]
    routing_rules.json     — List[CmsRoutingRule.to_dict()]
    images.json            — List[CmsImage.to_dict()]
    images/<file_path>     — raw image bytes (present when source file is readable)

Conflict strategies (import):
    'add'      — skip records whose slug (or name for routing rules) already exists.
    'index'    — on slug conflict append -2, -3, … until a free slug is found.
    'drop_all' — purge each present section first (reverse FK order), then insert.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from uuid import uuid4

if TYPE_CHECKING:
    pass

_VERSION = "1.0"

VALID_SECTIONS = frozenset(
    (
        "categories",
        "styles",
        "widgets",
        "layouts",
        "pages",
        "routing_rules",
        "images",
    )
)


class CmsImportExportService:
    """Single-responsibility service: CMS bulk export and import."""

    def __init__(
        self,
        category_repo,
        style_repo,
        widget_repo,
        layout_repo,
        page_repo,
        routing_repo,
        image_repo,
        lw_repo,
        file_storage,
    ) -> None:
        self._cat = category_repo
        self._style = style_repo
        self._widget = widget_repo
        self._layout = layout_repo
        self._page = page_repo
        self._routing = routing_repo
        self._image = image_repo
        self._lw = lw_repo
        self._fs = file_storage

    # ── PUBLIC API ─────────────────────────────────────────────────────────────

    def export(self, sections: List[str]) -> bytes:
        """Return a ZIP file as bytes containing the requested sections."""
        effective = (
            set(VALID_SECTIONS)
            if ("all" in sections or "everything" in sections)
            else set(sections) & VALID_SECTIONS
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", self._manifest(sorted(effective)))

            if "categories" in effective:
                zf.writestr(
                    "categories.json",
                    _json([c.to_dict() for c in self._cat.find_all()]),
                )

            if "styles" in effective:
                zf.writestr(
                    "styles.json",
                    _json([s.to_dict() for s in self._paginated(self._style)]),
                )

            if "widgets" in effective:
                zf.writestr(
                    "widgets.json",
                    _json([w.to_dict() for w in self._paginated(self._widget)]),
                )

            if "layouts" in effective:
                layouts = []
                for lay in self._paginated(self._layout):
                    d = lay.to_dict()
                    d["widget_assignments"] = self._layout_assignments(lay)
                    layouts.append(d)
                zf.writestr("layouts.json", _json(layouts))

            if "pages" in effective:
                pages = []
                for p in self._paginated(self._page):
                    d = p.to_dict()
                    d["category_slug"] = self._slug_of(self._cat, p.category_id)
                    d["layout_slug"] = self._slug_of(self._layout, p.layout_id)
                    d["style_slug"] = self._slug_of(self._style, p.style_id)
                    pages.append(d)
                zf.writestr("pages.json", _json(pages))

            if "routing_rules" in effective:
                zf.writestr(
                    "routing_rules.json",
                    _json([r.to_dict() for r in self._routing.find_all()]),
                )

            if "images" in effective:
                images = []
                for img in self._paginated(self._image):
                    d = img.to_dict()
                    if img.file_path:
                        try:
                            raw = self._fs.read(img.file_path)
                            zf.writestr(f"images/{img.file_path}", raw)
                        except Exception:
                            pass
                    images.append(d)
                zf.writestr("images.json", _json(images))

        buf.seek(0)
        return buf.read()

    def import_zip(self, zip_data: bytes, conflict_strategy: str) -> dict:
        """Import from a ZIP.  Returns {'imported': {...}, 'errors': [...]}."""
        counters: Dict[str, int] = {}
        errors: List[str] = []

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = set(zf.namelist())

            def _load(name: str) -> list:
                return json.loads(zf.read(name))

            if conflict_strategy == "drop_all":
                self._drop_sections(names)

            # Import in FK dependency order
            if "categories.json" in names:
                n, e = self._import_entities(
                    _load("categories.json"),
                    conflict_strategy,
                    repo=self._cat,
                    factory=self._make_category,
                )
                counters["categories"] = n
                errors.extend(e)

            if "styles.json" in names:
                n, e = self._import_entities(
                    _load("styles.json"),
                    conflict_strategy,
                    repo=self._style,
                    factory=self._make_style,
                )
                counters["styles"] = n
                errors.extend(e)

            if "widgets.json" in names:
                n, e = self._import_entities(
                    _load("widgets.json"),
                    conflict_strategy,
                    repo=self._widget,
                    factory=self._make_widget,
                )
                counters["widgets"] = n
                errors.extend(e)

            if "layouts.json" in names:
                n, e = self._import_layouts(_load("layouts.json"), conflict_strategy)
                counters["layouts"] = n
                errors.extend(e)

            if "pages.json" in names:
                n, e = self._import_pages(_load("pages.json"), conflict_strategy)
                counters["pages"] = n
                errors.extend(e)

            if "routing_rules.json" in names:
                n, e = self._import_routing_rules(
                    _load("routing_rules.json"), conflict_strategy
                )
                counters["routing_rules"] = n
                errors.extend(e)

            if "images.json" in names:
                n, e = self._import_images(
                    _load("images.json"), zf, names, conflict_strategy
                )
                counters["images"] = n
                errors.extend(e)

        return {"imported": counters, "errors": errors}

    # ── EXPORT HELPERS ─────────────────────────────────────────────────────────

    def _manifest(self, sections: List[str]) -> str:
        return json.dumps(
            {
                "version": _VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "sections": sections,
            },
            indent=2,
        )

    def _paginated(self, repo) -> list:
        return repo.find_all(page=1, per_page=100000)["items"]

    def _slug_of(self, repo, obj_id) -> Optional[str]:
        if not obj_id:
            return None
        obj = repo.find_by_id(str(obj_id))
        return obj.slug if obj else None

    def _layout_assignments(self, layout) -> list:
        result = []
        for a in self._lw.find_by_layout(str(layout.id)):
            w = self._widget.find_by_id(str(a.widget_id))
            result.append(
                {
                    "widget_slug": w.slug if w else None,
                    "area_name": a.area_name,
                    "sort_order": a.sort_order,
                }
            )
        return result

    # ── DROP-ALL HELPERS ───────────────────────────────────────────────────────

    def _drop_sections(self, names: set) -> None:
        # Reverse FK order: pages → layouts → widgets → styles → categories
        if "pages.json" in names:
            ids = [str(p.id) for p in self._paginated(self._page)]
            if ids:
                self._page.bulk_delete(ids)
        if "layouts.json" in names:
            ids = [str(l.id) for l in self._paginated(self._layout)]
            if ids:
                self._layout.bulk_delete(ids)
        if "widgets.json" in names:
            ids = [str(w.id) for w in self._paginated(self._widget)]
            if ids:
                self._widget.bulk_delete(ids)
        if "styles.json" in names:
            ids = [str(s.id) for s in self._paginated(self._style)]
            if ids:
                self._style.bulk_delete(ids)
        if "categories.json" in names:
            for c in self._cat.find_all():
                self._cat.delete(str(c.id))
        if "routing_rules.json" in names:
            for r in self._routing.find_all():
                self._routing.delete(str(r.id))
        if "images.json" in names:
            ids = [str(i.id) for i in self._paginated(self._image)]
            if ids:
                self._image.bulk_delete(ids)

    # ── GENERIC SLUG-BASED IMPORT ──────────────────────────────────────────────

    def _free_slug(self, base: str, repo, strategy: str) -> str:
        """Return the slug to use (empty string = skip this record)."""
        if strategy == "drop_all" or not repo.find_by_slug(base):
            return base
        if strategy == "add":
            return ""  # skip
        # 'index': append -2, -3, …
        for i in range(2, 10_000):
            candidate = f"{base}-{i}"
            if not repo.find_by_slug(candidate):
                return candidate
        return f"{base}-{uuid4().hex[:6]}"

    def _import_entities(
        self,
        records: list,
        strategy: str,
        repo,
        factory,
    ) -> Tuple[int, List[str]]:
        count, errors = 0, []
        for rec in records:
            try:
                slug = self._free_slug(rec["slug"], repo, strategy)
                if not slug:
                    continue
                obj = factory(rec, slug)
                repo.save(obj)
                count += 1
            except Exception as ex:
                errors.append(f"{rec.get('slug', '?')}: {ex}")
        return count, errors

    # ── SPECIALISED IMPORTERS ──────────────────────────────────────────────────

    def _import_layouts(self, records: list, strategy: str) -> Tuple[int, List[str]]:
        count, errors = 0, []
        for rec in records:
            try:
                slug = self._free_slug(rec["slug"], self._layout, strategy)
                if not slug:
                    continue
                lay = self._make_layout(rec, slug)
                saved = self._layout.save(lay)
                assignments = [
                    {
                        "widget_id": str(w.id),
                        "area_name": a["area_name"],
                        "sort_order": a.get("sort_order", 0),
                    }
                    for a in rec.get("widget_assignments", [])
                    if a.get("widget_slug")
                    and (w := self._widget.find_by_slug(a["widget_slug"]))
                ]
                if assignments:
                    self._lw.replace_for_layout(str(saved.id), assignments)
                count += 1
            except Exception as ex:
                errors.append(f"{rec.get('slug', '?')}: {ex}")
        return count, errors

    def _import_pages(self, records: list, strategy: str) -> Tuple[int, List[str]]:
        count, errors = 0, []
        for rec in records:
            try:
                slug = self._free_slug(rec["slug"], self._page, strategy)
                if not slug:
                    continue
                self._page.save(self._make_page(rec, slug))
                count += 1
            except Exception as ex:
                errors.append(f"{rec.get('slug', '?')}: {ex}")
        return count, errors

    def _import_routing_rules(
        self, records: list, strategy: str
    ) -> Tuple[int, List[str]]:
        # Routing rules use 'name' (not slug) as identity key
        count, errors = 0, []
        existing = {r.name for r in self._routing.find_all()}
        for rec in records:
            try:
                name = rec.get("name", "")
                if strategy != "drop_all" and name in existing:
                    if strategy == "add":
                        continue
                    i = 2
                    while f"{name}-{i}" in existing:
                        i += 1
                    name = f"{name}-{i}"
                self._routing.save(self._make_routing_rule(rec, name))
                existing.add(name)
                count += 1
            except Exception as ex:
                errors.append(f"{rec.get('name', '?')}: {ex}")
        return count, errors

    def _import_images(
        self,
        records: list,
        zf: zipfile.ZipFile,
        names: set,
        strategy: str,
    ) -> Tuple[int, List[str]]:
        count, errors = 0, []
        for rec in records:
            try:
                slug = self._free_slug(rec["slug"], self._image, strategy)
                if not slug:
                    continue
                file_path = rec.get("file_path", "")
                zip_path = f"images/{file_path}"
                if zip_path in names:
                    self._fs.save(zf.read(zip_path), file_path)
                self._image.save(self._make_image(rec, slug, file_path))
                count += 1
            except Exception as ex:
                errors.append(f"{rec.get('slug', '?')}: {ex}")
        return count, errors

    # ── MODEL FACTORIES ────────────────────────────────────────────────────────

    def _make_category(self, rec: dict, slug: str):
        from plugins.cms.src.models.cms_category import CmsCategory

        obj = CmsCategory()
        obj.id = uuid4()
        obj.slug = slug
        obj.name = rec.get("name", slug)
        obj.parent_id = None
        obj.sort_order = rec.get("sort_order", 0)
        return obj

    def _make_style(self, rec: dict, slug: str):
        from plugins.cms.src.models.cms_style import CmsStyle

        obj = CmsStyle()
        obj.id = uuid4()
        obj.slug = slug
        obj.name = rec.get("name", slug)
        obj.source_css = rec.get("source_css", "")
        obj.sort_order = rec.get("sort_order", 0)
        obj.is_active = rec.get("is_active", True)
        return obj

    def _make_widget(self, rec: dict, slug: str):
        from plugins.cms.src.models.cms_widget import CmsWidget

        obj = CmsWidget()
        obj.id = uuid4()
        obj.slug = slug
        obj.name = rec.get("name", slug)
        obj.widget_type = rec.get("widget_type", "html")
        obj.content_json = rec.get("content_json")
        obj.source_css = rec.get("source_css")
        obj.config = rec.get("config")
        obj.sort_order = rec.get("sort_order", 0)
        obj.is_active = rec.get("is_active", True)
        return obj

    def _make_layout(self, rec: dict, slug: str):
        from plugins.cms.src.models.cms_layout import CmsLayout

        obj = CmsLayout()
        obj.id = uuid4()
        obj.slug = slug
        obj.name = rec.get("name", slug)
        obj.description = rec.get("description", "")
        obj.areas = rec.get("areas", [])
        obj.sort_order = rec.get("sort_order", 0)
        obj.is_active = rec.get("is_active", True)
        return obj

    def _make_page(self, rec: dict, slug: str):
        from plugins.cms.src.models.cms_page import CmsPage

        obj = CmsPage()
        obj.id = uuid4()
        obj.slug = slug
        obj.name = rec.get("name", slug)
        obj.language = rec.get("language", "en")
        obj.content_json = rec.get("content_json", {})
        obj.content_html = rec.get("content_html")
        obj.source_css = rec.get("source_css")
        obj.is_published = rec.get("is_published", False)
        obj.sort_order = rec.get("sort_order", 0)
        obj.meta_title = rec.get("meta_title")
        obj.meta_description = rec.get("meta_description")
        obj.meta_keywords = rec.get("meta_keywords")
        obj.og_title = rec.get("og_title")
        obj.og_description = rec.get("og_description")
        obj.og_image_url = rec.get("og_image_url")
        obj.canonical_url = rec.get("canonical_url")
        obj.robots = rec.get("robots", "index,follow")
        obj.schema_json = rec.get("schema_json")

        # Resolve FK by slug
        def _resolve(repo, slug_val):
            if not slug_val:
                return None
            obj = repo.find_by_slug(slug_val)
            return obj.id if obj else None

        obj.category_id = _resolve(self._cat, rec.get("category_slug"))
        obj.layout_id = _resolve(self._layout, rec.get("layout_slug"))
        obj.style_id = _resolve(self._style, rec.get("style_slug"))
        return obj

    def _make_routing_rule(self, rec: dict, name: str):
        from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule

        obj = CmsRoutingRule()
        obj.id = uuid4()
        obj.name = name
        obj.is_active = rec.get("is_active", True)
        obj.priority = rec.get("priority", 0)
        obj.match_type = rec.get("match_type", "default")
        obj.match_value = rec.get("match_value")
        obj.target_slug = rec.get("target_slug", "")
        obj.redirect_code = rec.get("redirect_code", 302)
        obj.is_rewrite = rec.get("is_rewrite", False)
        obj.layer = rec.get("layer", "middleware")
        return obj

    def _make_image(self, rec: dict, slug: str, file_path: str):
        from plugins.cms.src.models.cms_image import CmsImage

        obj = CmsImage()
        obj.id = uuid4()
        obj.slug = slug
        obj.caption = rec.get("caption", "")
        obj.file_path = file_path
        obj.url_path = rec.get("url_path", f"/uploads/{file_path}")
        obj.mime_type = rec.get("mime_type", "image/jpeg")
        obj.file_size_bytes = rec.get("file_size_bytes", 0)
        obj.width_px = rec.get("width_px")
        obj.height_px = rec.get("height_px")
        obj.alt_text = rec.get("alt_text", "")
        return obj


# ── Module-level helpers ───────────────────────────────────────────────────────


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
