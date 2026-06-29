"""CMS entity exchangers for the S46 data-exchange seam (S46.5).

These adapters expose the CMS unified content model through the core
``EntityExchanger`` contract so CMS entities appear on the generic Settings →
Import/Export page and the per-list controls — *coexisting* with the bespoke
``/admin/cms/*`` export/import routes (one shared service underneath, DRY).

Design notes:

* **DRY** — the post / term exchangers delegate to the existing
  ``PostImportExportService`` / ``TermImportExportService`` (the single home for
  the VBWD-standard CMS envelopes); they do not reimplement serialisation. The
  post exchanger carries the S55 ``content_blocks`` + ``page_assignments`` round
  trip because the service does (when wired with the optional area repos).
* **Reused perms** — CMS already ships ``cms.pages.*`` / ``cms.images.*`` /
  ``cms.widgets.*`` / ``cms.layouts.manage`` / ``cms.styles.manage``. Rather
  than minting a parallel ``cms_posts.export`` permission family, each exchanger
  declares its cluster as ``content`` and overrides ``export_permission`` /
  ``import_permission`` to map onto the existing CMS permission (single source).
* **No core change** — registration happens in ``CmsPlugin.on_enable`` via the
  injected ``db.session`` + file storage; core imports no ``plugins.*`` module.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID (one exchanger per
entity, narrow ports); DI (session + storage injected); DRY (delegate to the
existing services/repos); Liskov (every exchanger honours the base contract;
the images exchanger emits a richer envelope without breaking callers); clean
code; no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import base64
from typing import Any, List, Optional

from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.envelope import validate_envelope
from vbwd.services.data_exchange.port import (
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    ZipExport,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

# CMS entities are grouped under their own UI cluster (the generic seam treats
# any non-"settings" cluster via per-entity permissions, which we map onto the
# existing CMS permissions below).
CMS_CLUSTER = "content"

# Existing CMS permissions (single source — declared in CmsPlugin.admin_permissions).
PERM_PAGES_VIEW = "cms.pages.view"
PERM_PAGES_MANAGE = "cms.pages.manage"
PERM_IMAGES_VIEW = "cms.images.view"
PERM_IMAGES_MANAGE = "cms.images.manage"
PERM_WIDGETS_VIEW = "cms.widgets.view"
PERM_WIDGETS_MANAGE = "cms.widgets.manage"
PERM_LAYOUTS_MANAGE = "cms.layouts.manage"
PERM_STYLES_MANAGE = "cms.styles.manage"


class _SessionModelRepository:
    """Narrow model repo satisfying the ``BaseModelExchanger`` contract.

    Mirrors core's ``core_exchangers._SessionModelRepository`` — the CMS repos
    expose paginated ``find_all`` dicts rather than the four flat methods the
    base exchanger needs, so this adapter provides exactly those (ISP) without
    touching the existing repos.
    """

    def __init__(self, session: Any, model_class: type, natural_key: str) -> None:
        self._session = session
        self._model_class = model_class
        self._natural_key = natural_key

    def find_all(self) -> List[Any]:
        return self._session.query(self._model_class).all()

    def find_by_natural_key(self, value: Any) -> Optional[Any]:
        column = getattr(self._model_class, self._natural_key)
        return self._session.query(self._model_class).filter(column == value).first()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete_all(self) -> None:
        self._session.query(self._model_class).delete()


class _CmsModelExchanger(BaseModelExchanger):
    """A ``BaseModelExchanger`` whose export/import perms map onto CMS perms.

    The generic registry gates non-settings clusters by ``export_permission`` /
    ``import_permission``; this subclass returns the existing CMS permission so
    the gate reuses the CMS RBAC (no parallel ``<entity>.export`` perm family).
    """

    def __init__(
        self,
        *,
        view_permission: str,
        manage_permission: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._view_permission = view_permission
        self._manage_permission = manage_permission

    @property
    def export_permission(self) -> str:
        return self._view_permission

    @property
    def import_permission(self) -> str:
        return self._manage_permission


class _SingletonDefaultMixin:
    """Import-side handling for entities with a partial-unique "only one row may
    have ``is_default=True``" index (``cms_style`` → ``ix_cms_style_default_singleton``,
    ``cms_layout`` → ``ix_cms_layout_default_singleton``).

    Importing a row flagged ``is_default=True`` whose slug differs from the row
    that currently holds the default violates that index the moment the new row
    flushes (two ``is_default=True`` rows coexist) — surfacing as a 500. Before
    applying such a row we demote the incumbent default(s) and flush, so the
    singleton invariant holds at every flush boundary. Dry-runs mutate nothing,
    so they skip the demotion. Last-default-wins when an import carries several.
    """

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        if not dry_run and row.get("is_default"):
            self._demote_current_default(row.get(self.natural_key))
        super()._import_row(row, index, result, dry_run=dry_run)

    def _demote_current_default(self, incoming_key: Any) -> None:
        model_class = self._model_class
        current_defaults = (
            self._session.query(model_class)
            .filter(model_class.is_default.is_(True))
            .all()
        )
        demoted = False
        for existing in current_defaults:
            if getattr(existing, self.natural_key) == incoming_key:
                continue
            existing.is_default = False
            demoted = True
        if demoted:
            # Flush the demotion before the incoming default row flushes, so the
            # partial-unique singleton index never sees two defaults at once.
            self._session.flush()


class _CmsWidgetsExchanger(_CmsModelExchanger):
    """``cms_widgets`` carrying the ``cms_menu_item`` tree of menu widgets.

    Menu links live in the separate ``cms_menu_item`` table, not in the
    widget's ``config``/``content_json`` — a scalar-only export is structurally
    empty for menus and import is equally lossy (S68 Bug A). Mirrors the S61
    ``booking_resources`` precedent (a thin subclass carries the relation):
    export attaches ``menu_items`` (item dicts keep ``id``/``parent_id`` as
    placeholder ids so the import two-pass remap works — the same payload the
    bespoke ``CmsWidgetService.export_widget`` emits); import routes them
    through ``CmsMenuItemRepository.replace_tree`` (already idempotent).
    Non-menu widgets are unchanged (no ``menu_items`` key).
    """

    MENU_WIDGET_TYPE = "menu"

    def __init__(self, *, menu_item_repository: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._menu_item_repository = menu_item_repository

    def _serialise_row(self, row: Any, *, include_pii: bool) -> dict:
        result = super()._serialise_row(row, include_pii=include_pii)
        if row.widget_type == self.MENU_WIDGET_TYPE:
            result["menu_items"] = [
                item.to_dict()
                for item in self._menu_item_repository.find_tree_by_widget(str(row.id))
            ]
        return result

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        menu_items = row.get("menu_items")
        scalar_row = {key: value for key, value in row.items() if key != "menu_items"}
        super()._import_row(scalar_row, index, result, dry_run=dry_run)
        if dry_run or not menu_items:
            return
        if scalar_row.get("widget_type") != self.MENU_WIDGET_TYPE:
            return
        widget = self._repository.find_by_natural_key(scalar_row[self.natural_key])
        if widget is not None:
            self._menu_item_repository.replace_tree(str(widget.id), menu_items)


class _CmsStylesExchanger(_SingletonDefaultMixin, _CmsModelExchanger):
    """``cms_styles`` — a flat-scalar model exchanger that additionally honours
    the singleton-default invariant on import (see :class:`_SingletonDefaultMixin`)."""


class _CmsLayoutsExchanger(_SingletonDefaultMixin, _CmsModelExchanger):
    """``cms_layouts`` carrying its widget PLACEMENTS (the ``cms_layout_widget``
    rows) by widget slug.

    A layout's "which widget sits in which area" mapping lives in the separate
    ``cms_layout_widget`` table, not on the layout row — a scalar-only export
    loses every placement, forcing a manual ``PUT /admin/cms/layouts/<id>/
    widgets`` after import. Mirrors the ``_CmsWidgetsExchanger`` (menu items)
    precedent: export attaches ``widget_assignments``; import pops them, runs
    the scalar upsert, then replace-sets the placements via
    ``CmsLayoutWidgetRepository.replace_for_layout``.

    Portability: a placement is carried as ``area_name`` + ``widget_slug`` +
    ``sort_order``. The per-instance ``widget_id`` and per-placement
    ``required_access_level_ids`` (access-level UUIDs that do not port across
    instances) are deliberately NOT emitted — per-placement access gating is
    not carried by this exchanger (out of scope for this round-trip gap).

    Import order: widgets must exist before a layout's placements resolve (the
    manifest/full-instance import does widgets before layouts). If a
    ``widget_slug`` is unknown the placement is reported as a row error and
    skipped — the layout still imports and the other placements still apply
    (safe degrade, never a 500/crash).
    """

    def __init__(
        self,
        *,
        layout_widget_repository: Any,
        widget_repository: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._layout_widget_repository = layout_widget_repository
        self._widget_repository = widget_repository

    def _serialise_row(self, row: Any, *, include_pii: bool) -> dict:
        result = super()._serialise_row(row, include_pii=include_pii)
        result["widget_assignments"] = self._serialise_assignments(row)
        return result

    def _serialise_assignments(self, layout: Any) -> List[dict]:
        assignments: List[dict] = []
        for placement in self._layout_widget_repository.find_by_layout(layout.id):
            widget = self._widget_repository.find_by_id(str(placement.widget_id))
            if widget is None:
                # Defensive: a dangling placement whose widget no longer exists.
                continue
            assignments.append(
                {
                    "area_name": placement.area_name,
                    "widget_slug": widget.slug,
                    "sort_order": placement.sort_order,
                }
            )
        assignments.sort(key=lambda item: (item["area_name"], item["sort_order"]))
        return assignments

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        assignments = row.get("widget_assignments")
        scalar_row = {
            key: value for key, value in row.items() if key != "widget_assignments"
        }
        super()._import_row(scalar_row, index, result, dry_run=dry_run)
        if dry_run or not assignments:
            return
        layout = self._repository.find_by_natural_key(scalar_row[self.natural_key])
        if layout is None:
            return
        self._apply_assignments(layout, assignments, index, result)

    def _apply_assignments(
        self,
        layout: Any,
        assignments: List[dict],
        index: int,
        result: ImportResult,
    ) -> None:
        resolved: List[dict] = []
        for assignment in assignments:
            widget_slug = assignment.get("widget_slug")
            widget = (
                self._widget_repository.find_by_slug(widget_slug)
                if widget_slug
                else None
            )
            if widget is None:
                result.errors.append(
                    {
                        "row": index,
                        "reason": (
                            f"layout '{layout.slug}' references unknown widget_slug "
                            f"'{widget_slug}'; placement skipped"
                        ),
                    }
                )
                continue
            resolved.append(
                {
                    "widget_id": str(widget.id),
                    "area_name": assignment.get("area_name"),
                    "sort_order": assignment.get("sort_order", 0),
                    "required_access_level_ids": [],
                }
            )
        self._layout_widget_repository.replace_for_layout(str(layout.id), resolved)


# ── posts (delegates to PostImportExportService) ──────────────────────────────


class CmsPostsExchanger(EntityExchanger):
    """Unified ``cms_post`` (page/post/custom), keyed by ``slug``.

    Delegates to ``PostImportExportService`` (the existing VBWD-standard post
    envelope) so the per-row shape — including the S55 ``content_blocks`` +
    ``page_assignments`` — is produced in exactly one place.
    """

    entity_key = "cms_posts"
    label = "CMS Posts"
    cluster = CMS_CLUSTER
    natural_key = "slug"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def __init__(self, post_import_export_service: Any) -> None:
        self._service = post_import_export_service

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        rows = self._service.export_posts(ids=selector.ids).get("items", [])
        return Envelope(entity_key=self.entity_key, rows=rows)

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        rows = validate_envelope(payload, self.entity_key)
        if dry_run:
            # The post service commits per row; for a preview we only count.
            result.created = len(rows)
            return result
        outcome = self._service.import_posts({"items": rows})
        result.created = outcome.get("created", 0)
        result.updated = outcome.get("updated", 0)
        return result

    @property
    def export_permission(self) -> str:
        return PERM_PAGES_VIEW

    @property
    def import_permission(self) -> str:
        return PERM_PAGES_MANAGE


# ── terms (delegates to TermImportExportService) ──────────────────────────────


class CmsTermsExchanger(EntityExchanger):
    """Unified ``cms_term`` (category/tag/custom), keyed by ``slug``."""

    entity_key = "cms_terms"
    label = "CMS Terms"
    cluster = CMS_CLUSTER
    natural_key = "slug"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def __init__(self, term_import_export_service: Any) -> None:
        self._service = term_import_export_service

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        rows = self._service.export_terms(ids=selector.ids).get("items", [])
        return Envelope(entity_key=self.entity_key, rows=rows)

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        rows = validate_envelope(payload, self.entity_key)
        if dry_run:
            result.created = len(rows)
            return result
        outcome = self._service.import_terms({"items": rows})
        result.created = outcome.get("created", 0)
        result.updated = outcome.get("updated", 0)
        return result

    @property
    def export_permission(self) -> str:
        return PERM_PAGES_VIEW

    @property
    def import_permission(self) -> str:
        return PERM_PAGES_MANAGE


# ── images (ZIP + assets: binary travels base64 in the JSON envelope) ─────────


class CmsImagesExchanger(EntityExchanger):
    """``cms_image`` rows, keyed by ``slug``, carrying their binary content.

    Images are not flat scalar rows — each row references a file on disk. So the
    envelope nests the raw bytes (base64) under ``data`` so the JSON export is
    self-contained and round-trips through the generic JSON route AND the ZIP
    bundle (the bundle simply wraps the same envelope). The file is written back
    through the same ``IFileStorage`` the CMS gallery uses, so a round-trip
    reproduces both the row and the binary.
    """

    entity_key = "cms_images"
    label = "CMS Images"
    cluster = CMS_CLUSTER
    natural_key = "slug"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "zip"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    # The portable, id-free fields of an image row.
    _ROW_FIELDS = (
        "slug",
        "caption",
        "file_path",
        "url_path",
        "mime_type",
        "file_size_bytes",
        "width_px",
        "height_px",
        "alt_text",
        "og_image_url",
        "robots",
        "schema_json",
    )

    def __init__(self, session: Any, image_repository: Any, file_storage: Any) -> None:
        self._session = session
        self._repo = image_repository
        self._storage = file_storage

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        images = self._repo.find_all(page=1, per_page=100000).get("items", [])
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            images = [
                image
                for image in images
                if str(image.id) in wanted or (image.slug and image.slug in wanted)
            ]
        rows = [self._serialise(image) for image in images]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _serialise(self, image: Any) -> dict:
        row = {
            field_name: getattr(image, field_name) for field_name in self._ROW_FIELDS
        }
        row["data"] = self._read_binary(image.file_path)
        return row

    def _read_binary(self, file_path: Optional[str]) -> Optional[str]:
        if not file_path:
            return None
        raw = self._read_raw(file_path)
        if raw is None:
            return None
        return base64.b64encode(raw).decode("ascii")

    def _read_raw(self, file_path: Optional[str]) -> Optional[bytes]:
        if not file_path:
            return None
        try:
            return self._storage.read(file_path)
        except (FileNotFoundError, OSError, ValueError):
            return None

    def export_zip(self, selector: ExportSelector, *, include_pii: bool) -> ZipExport:
        """Export image rows referencing their binary as an ``assets/`` file.

        Unlike :meth:`export` (which inlines the bytes as base64 ``data`` so the
        JSON download is self-contained), the zip path puts the raw bytes in the
        bundle's ``assets/`` directory and the row references them by an
        ``asset_file`` filename — so the archive contains real image files.
        """
        envelope_rows = self.export(selector, include_pii=include_pii).rows
        rows: List[dict] = []
        assets: dict = {}
        for row in envelope_rows:
            asset_row = {key: value for key, value in row.items() if key != "data"}
            raw = self._read_raw(row.get("file_path"))
            if raw is not None:
                asset_file = self._asset_filename(row)
                asset_row["asset_file"] = asset_file
                assets[asset_file] = raw
            rows.append(asset_row)
        return ZipExport(rows=rows, assets=assets)

    def attach_assets(self, envelope: dict, assets: dict) -> dict:
        """Re-inline ``asset_file`` bytes as base64 ``data`` so ``import_`` works.

        The reverse of :meth:`export_zip`: the existing base64 ``import_`` path is
        the single home for writing the binary back, so the bundle import maps the
        asset bytes onto ``data`` and removes the now-redundant ``asset_file``.
        """
        rows = validate_envelope(envelope, self.entity_key)
        for row in rows:
            asset_file = row.pop("asset_file", None)
            if asset_file and asset_file in assets:
                row["data"] = base64.b64encode(assets[asset_file]).decode("ascii")
        return envelope

    def _asset_filename(self, row: dict) -> str:
        slug = row.get("slug") or "image"
        file_path = row.get("file_path") or ""
        _, _, extension = file_path.rpartition(".")
        return f"{slug}.{extension}" if extension and extension != file_path else slug

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        from plugins.cms.src.models.cms_image import CmsImage

        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        try:
            for index, row in enumerate(rows):
                self._import_row(row, index, result, CmsImage, dry_run=dry_run)
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _import_row(
        self,
        row: dict,
        index: int,
        result: ImportResult,
        model_class: type,
        *,
        dry_run: bool,
    ) -> None:
        slug = row.get("slug")
        if not slug:
            result.errors.append({"row": index, "reason": "missing natural key 'slug'"})
            return
        existing = self._repo.find_by_slug(slug)
        if not dry_run:
            image = existing or model_class()
            self._apply(image, row)
            self._session.add(image)
            self._write_binary(row)
        if existing is not None:
            result.updated += 1
        else:
            result.created += 1

    def _apply(self, image: Any, row: dict) -> None:
        for field_name in self._ROW_FIELDS:
            if field_name in row:
                setattr(image, field_name, row[field_name])

    def _write_binary(self, row: dict) -> None:
        encoded = row.get("data")
        file_path = row.get("file_path")
        if not encoded or not file_path:
            return
        self._storage.save(base64.b64decode(encoded), file_path)

    @property
    def export_permission(self) -> str:
        return PERM_IMAGES_VIEW

    @property
    def import_permission(self) -> str:
        return PERM_IMAGES_MANAGE


# ── factory + registration ────────────────────────────────────────────────────


def build_cms_exchangers(
    session: Any,
    *,
    file_storage: Any,
) -> List[EntityExchanger]:
    """Construct the CMS exchangers bound to ``session`` + ``file_storage``."""
    from plugins.cms.src.models.cms_layout import CmsLayout
    from plugins.cms.src.models.cms_style import CmsStyle
    from plugins.cms.src.models.cms_widget import CmsWidget
    from plugins.cms.src.repositories.cms_image_repository import CmsImageRepository
    from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
    from plugins.cms.src.repositories.cms_layout_widget_repository import (
        CmsLayoutWidgetRepository,
    )
    from plugins.cms.src.repositories.cms_menu_item_repository import (
        CmsMenuItemRepository,
    )
    from plugins.cms.src.repositories.cms_style_repository import CmsStyleRepository
    from plugins.cms.src.repositories.cms_widget_repository import CmsWidgetRepository
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.post_term_repository import PostTermRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.repositories.cms_post_content_block_repository import (
        CmsPostContentBlockRepository,
    )
    from plugins.cms.src.repositories.cms_post_widget_repository import (
        CmsPostWidgetRepository,
    )
    from plugins.cms.src.services.post_import_export_service import (
        PostImportExportService,
    )
    from plugins.cms.src.services.term_import_export_service import (
        TermImportExportService,
    )

    post_service = PostImportExportService(
        post_repo=PostRepository(session),
        layout_repo=CmsLayoutRepository(session),
        style_repo=CmsStyleRepository(session),
        term_repo=TermRepository(session),
        post_term_repo=PostTermRepository(session),
        content_block_repo=CmsPostContentBlockRepository(session),
        post_widget_repo=CmsPostWidgetRepository(session),
        widget_repo=CmsWidgetRepository(session),
    )
    term_service = TermImportExportService(TermRepository(session))

    return [
        CmsPostsExchanger(post_service),
        CmsTermsExchanger(term_service),
        _CmsLayoutsExchanger(
            entity_key="cms_layouts",
            label="CMS Layouts",
            cluster=CMS_CLUSTER,
            natural_key="slug",
            model_class=CmsLayout,
            repository=_SessionModelRepository(session, CmsLayout, "slug"),
            layout_widget_repository=CmsLayoutWidgetRepository(session),
            widget_repository=CmsWidgetRepository(session),
            session=session,
            public_fields=[
                "slug",
                "name",
                "description",
                "areas",
                "sort_order",
                "is_active",
                "is_default",
            ],
            view_permission=PERM_PAGES_VIEW,
            manage_permission=PERM_LAYOUTS_MANAGE,
        ),
        _CmsStylesExchanger(
            entity_key="cms_styles",
            label="CMS Styles",
            cluster=CMS_CLUSTER,
            natural_key="slug",
            model_class=CmsStyle,
            repository=_SessionModelRepository(session, CmsStyle, "slug"),
            session=session,
            public_fields=[
                "slug",
                "name",
                "source_css",
                "sort_order",
                "is_active",
                "is_default",
            ],
            view_permission=PERM_PAGES_VIEW,
            manage_permission=PERM_STYLES_MANAGE,
        ),
        _CmsWidgetsExchanger(
            entity_key="cms_widgets",
            label="CMS Widgets",
            cluster=CMS_CLUSTER,
            natural_key="slug",
            model_class=CmsWidget,
            repository=_SessionModelRepository(session, CmsWidget, "slug"),
            menu_item_repository=CmsMenuItemRepository(session),
            session=session,
            public_fields=[
                "slug",
                "name",
                "widget_type",
                "content_json",
                "source_css",
                "config",
                "sort_order",
                "is_active",
            ],
            view_permission=PERM_WIDGETS_VIEW,
            manage_permission=PERM_WIDGETS_MANAGE,
        ),
        CmsImagesExchanger(session, CmsImageRepository(session), file_storage),
    ]


def register_cms_exchangers(session: Any, *, file_storage: Any) -> None:
    """Register the CMS exchangers into the global registry (idempotent).

    Called from ``CmsPlugin.on_enable``. Re-registering replaces by key, so a
    repeat enable (per-test app) is clear-safe.
    """
    for exchanger in build_cms_exchangers(session, file_storage=file_storage):
        data_exchange_registry.register(exchanger)
