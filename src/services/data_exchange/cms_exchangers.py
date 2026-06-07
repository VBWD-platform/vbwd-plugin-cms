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
        rows = self._service.export_terms().get("items", [])
        if selector.ids:
            wanted = set(selector.ids)
            rows = [row for row in rows if row.get("slug") in wanted]
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
            wanted = set(selector.ids)
            images = [image for image in images if image.slug in wanted]
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
        try:
            raw = self._storage.read(file_path)
        except (FileNotFoundError, OSError, ValueError):
            return None
        return base64.b64encode(raw).decode("ascii")

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
        _CmsModelExchanger(
            entity_key="cms_layouts",
            label="CMS Layouts",
            cluster=CMS_CLUSTER,
            natural_key="slug",
            model_class=CmsLayout,
            repository=_SessionModelRepository(session, CmsLayout, "slug"),
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
        _CmsModelExchanger(
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
        _CmsModelExchanger(
            entity_key="cms_widgets",
            label="CMS Widgets",
            cluster=CMS_CLUSTER,
            natural_key="slug",
            model_class=CmsWidget,
            repository=_SessionModelRepository(session, CmsWidget, "slug"),
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
