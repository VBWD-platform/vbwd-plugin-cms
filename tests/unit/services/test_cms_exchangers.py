"""Unit: CMS entity exchangers (S46.5) — manifest metadata + registration.

No DB: asserts each exchanger declares the right ``entity_key`` / ``cluster`` /
``natural_key`` / ``supported_formats`` and that registration is idempotent and
clear-safe. Round-trip behaviour is covered by the integration suite (real PG).

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY (the post
+ term exchangers delegate to the existing import/export services); Liskov (the
images exchanger emits a richer envelope without breaking the base contract);
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vbwd.services.data_exchange.port import ExportSelector, ZipExport
from vbwd.services.data_exchange.registry import DataExchangeRegistry
from plugins.cms.src.services.data_exchange.cms_exchangers import (
    CMS_CLUSTER,
    CmsImagesExchanger,
    CmsPostsExchanger,
    CmsTermsExchanger,
    build_cms_exchangers,
    register_cms_exchangers,
)


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def storage():
    return MagicMock()


class TestManifestMetadata:
    def test_all_six_entities_present(self, session, storage):
        keys = {
            exchanger.entity_key
            for exchanger in build_cms_exchangers(session, file_storage=storage)
        }
        assert keys == {
            "cms_posts",
            "cms_terms",
            "cms_layouts",
            "cms_styles",
            "cms_widgets",
            "cms_images",
        }

    def test_clusters_are_content(self, session, storage):
        for exchanger in build_cms_exchangers(session, file_storage=storage):
            assert exchanger.cluster == CMS_CLUSTER

    def test_natural_keys_are_slug(self, session, storage):
        for exchanger in build_cms_exchangers(session, file_storage=storage):
            assert exchanger.natural_key == "slug"

    def test_no_secret_or_pii_fields(self, session, storage):
        for exchanger in build_cms_exchangers(session, file_storage=storage):
            assert exchanger.secret_fields == frozenset()
            assert exchanger.pii_fields == frozenset()

    def test_images_supports_zip(self, session, storage):
        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in build_cms_exchangers(session, file_storage=storage)
        }
        assert "zip" in by_key["cms_images"].supported_formats

    def test_exchangers_map_to_existing_cms_permissions(self, session, storage):
        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in build_cms_exchangers(session, file_storage=storage)
        }
        assert by_key["cms_posts"].export_permission == "cms.pages.view"
        assert by_key["cms_posts"].import_permission == "cms.pages.manage"
        assert by_key["cms_widgets"].import_permission == "cms.widgets.manage"
        assert by_key["cms_layouts"].import_permission == "cms.layouts.manage"
        assert by_key["cms_styles"].import_permission == "cms.styles.manage"
        assert by_key["cms_images"].import_permission == "cms.images.manage"


class TestRegistration:
    def test_register_is_idempotent_and_clear_safe(self, session, storage):
        registry = DataExchangeRegistry()
        import plugins.cms.src.services.data_exchange.cms_exchangers as module

        # Patch the module-level singleton the register helper writes into.
        original = module.data_exchange_registry
        module.data_exchange_registry = registry
        try:
            register_cms_exchangers(session, file_storage=storage)
            register_cms_exchangers(session, file_storage=storage)
            keys = [exchanger.entity_key for exchanger in registry.all()]
            assert len(keys) == len(set(keys))
            assert "cms_posts" in keys
        finally:
            module.data_exchange_registry = original


class TestPostsExchangerDelegation:
    def test_export_delegates_with_selector_ids(self):
        service = MagicMock()
        service.export_posts.return_value = {"items": [{"slug": "a"}]}
        exchanger = CmsPostsExchanger(service)
        envelope = exchanger.export(ExportSelector(ids=["a"]), include_pii=False)
        service.export_posts.assert_called_once_with(ids=["a"])
        assert envelope.rows == [{"slug": "a"}]

    def test_import_delegates_and_maps_counts(self):
        service = MagicMock()
        service.import_posts.return_value = {"created": 2, "updated": 1}
        exchanger = CmsPostsExchanger(service)
        result = exchanger.import_(
            {"cms_posts": [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]},
            mode="upsert",
            dry_run=False,
        )
        assert result.created == 2
        assert result.updated == 1
        service.import_posts.assert_called_once()

    def test_import_dry_run_does_not_write(self):
        service = MagicMock()
        exchanger = CmsPostsExchanger(service)
        result = exchanger.import_(
            {"cms_posts": [{"slug": "a"}]}, mode="upsert", dry_run=True
        )
        assert result.dry_run is True
        assert result.created == 1
        service.import_posts.assert_not_called()


class TestImagesZipAssetContract:
    """``export_zip`` carries the binary as a real asset file (not base64), and
    ``attach_assets`` reverses it so the base64 ``import_`` path round-trips."""

    def _exchanger(self, raw: bytes):
        image = SimpleNamespace(
            id="uuid-1",
            slug="hero",
            caption=None,
            file_path="images/hero.png",
            url_path="/uploads/images/hero.png",
            mime_type="image/png",
            file_size_bytes=len(raw),
            width_px=None,
            height_px=None,
            alt_text=None,
            og_image_url=None,
            robots=None,
            schema_json=None,
        )
        repo = MagicMock()
        repo.find_all.return_value = {"items": [image]}
        storage = MagicMock()
        storage.read.return_value = raw
        return CmsImagesExchanger(MagicMock(), repo, storage)

    def test_export_zip_returns_asset_bytes_and_asset_file_ref(self):
        raw = b"\x89PNG real-bytes"
        exchanger = self._exchanger(raw)
        zip_export = exchanger.export_zip(ExportSelector(all=True), include_pii=False)
        assert isinstance(zip_export, ZipExport)
        row = zip_export.rows[0]
        # The binary is referenced by an asset filename, not inlined as base64.
        assert "data" not in row
        asset_file = row["asset_file"]
        assert asset_file
        assert zip_export.assets[asset_file] == raw

    def test_attach_assets_reverses_into_base64_data(self):
        raw = b"\x89PNG real-bytes"
        exchanger = self._exchanger(raw)
        zip_export = exchanger.export_zip(ExportSelector(all=True), include_pii=False)
        envelope = {"cms_images": list(zip_export.rows)}
        rebuilt = exchanger.attach_assets(envelope, zip_export.assets)
        row = rebuilt["cms_images"][0]
        assert base64.b64decode(row["data"]) == raw

    def test_attach_assets_without_matching_asset_leaves_row(self):
        raw = b"bytes"
        exchanger = self._exchanger(raw)
        envelope = {"cms_images": [{"slug": "x", "asset_file": "missing.png"}]}
        rebuilt = exchanger.attach_assets(envelope, {})
        assert rebuilt["cms_images"][0].get("data") is None


class TestLayoutsExchangerExportShape:
    """``cms_layouts`` attaches its widget PLACEMENTS as ``widget_assignments``
    by widget slug — no per-instance ``widget_id`` / ``required_access_level_ids``."""

    def _exchanger(self, layout_widget_repo, widget_repo):
        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in build_cms_exchangers(MagicMock(), file_storage=MagicMock())
        }
        exchanger = by_key["cms_layouts"]
        exchanger._layout_widget_repository = layout_widget_repo
        exchanger._widget_repository = widget_repo
        return exchanger

    def test_export_emits_widget_assignments_by_slug(self):
        layout = SimpleNamespace(
            id="layout-uuid",
            slug="home",
            name="Home",
            description=None,
            areas=[{"name": "header"}, {"name": "footer"}],
            sort_order=0,
            is_active=True,
            is_default=True,
        )
        placements = [
            SimpleNamespace(area_name="footer", widget_id="w2", sort_order=0),
            SimpleNamespace(area_name="header", widget_id="w1", sort_order=1),
        ]
        layout_widget_repo = MagicMock()
        layout_widget_repo.find_by_layout.return_value = placements
        widget_repo = MagicMock()
        widget_repo.find_by_id.side_effect = lambda wid: {
            "w1": SimpleNamespace(id="w1", slug="nav-widget"),
            "w2": SimpleNamespace(id="w2", slug="footer-widget"),
        }[wid]

        exchanger = self._exchanger(layout_widget_repo, widget_repo)
        row = exchanger._serialise_row(layout, include_pii=False)

        assignments = row["widget_assignments"]
        # Deterministic order: by (area_name, sort_order).
        assert assignments == [
            {"area_name": "footer", "widget_slug": "footer-widget", "sort_order": 0},
            {"area_name": "header", "widget_slug": "nav-widget", "sort_order": 1},
        ]
        for assignment in assignments:
            assert "widget_id" not in assignment
            assert "required_access_level_ids" not in assignment

    def test_export_skips_placement_for_missing_widget(self):
        layout = SimpleNamespace(
            id="layout-uuid",
            slug="home",
            name="Home",
            description=None,
            areas=[],
            sort_order=0,
            is_active=True,
            is_default=False,
        )
        layout_widget_repo = MagicMock()
        layout_widget_repo.find_by_layout.return_value = [
            SimpleNamespace(area_name="header", widget_id="gone", sort_order=0),
        ]
        widget_repo = MagicMock()
        widget_repo.find_by_id.return_value = None

        exchanger = self._exchanger(layout_widget_repo, widget_repo)
        row = exchanger._serialise_row(layout, include_pii=False)
        assert row["widget_assignments"] == []


class TestTermsExchangerDelegation:
    def test_export_delegates_selector_ids_to_service(self):
        """The exchanger pushes the selector ids down to ``export_terms`` so the
        service does id-or-slug matching at the model level (the admin list
        sends primary ids, not slugs)."""
        service = MagicMock()
        service.export_terms.return_value = {"items": [{"slug": "news"}]}
        exchanger = CmsTermsExchanger(service)
        envelope = exchanger.export(
            ExportSelector(ids=["term-uuid-1"]), include_pii=False
        )
        service.export_terms.assert_called_once_with(ids=["term-uuid-1"])
        assert envelope.rows == [{"slug": "news"}]
