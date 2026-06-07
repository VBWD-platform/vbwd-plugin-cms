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
from unittest.mock import MagicMock

import pytest

from vbwd.services.data_exchange.port import ExportSelector
from vbwd.services.data_exchange.registry import DataExchangeRegistry
from plugins.cms.src.services.data_exchange.cms_exchangers import (
    CMS_CLUSTER,
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
