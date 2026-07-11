"""Unit tests for the curated three-page CMS applier's pure helpers.

The applier imports a CURATED ALLOWLIST of exactly three bundled page files
straight through ``PostImportExportService.import_posts`` (direct DB, no HTTP).
These tests exercise the pure, DB-free helpers: the envelope normaliser (which
must accept the plugin's native ``cms_posts`` envelope the import service does
NOT), the allowlist guard (so the applier can never drift into globbing the
whole pages directory and clobbering unrelated pages), and the bundled docs
page's own shape/content oracle.

Engineering requirements (binding, restated): TDD-first (these tests were
written before the applier and watched fail); DevOps-first (no DB needed here,
runs cold local + CI); SOLID/DI/DRY (normalisation lives in one helper reused
per file; the allowlist is the single source of what ships); Liskov (every
envelope shape maps to the same items-list contract); clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import json

import pytest

from plugins.cms.src.bin import apply_cms_pages as applier


class TestNormalizeEnvelopeItems:
    def test_items_envelope_returns_items(self):
        assert applier.normalize_envelope_items({"items": [{"slug": "a"}]}) == [
            {"slug": "a"}
        ]

    def test_cms_posts_envelope_returns_items(self):
        payload = {
            "vbwd_export": "cms_posts",
            "version": 1,
            "cms_posts": [{"slug": "b"}],
        }
        assert applier.normalize_envelope_items(payload) == [{"slug": "b"}]

    def test_bare_list_is_returned_as_items(self):
        assert applier.normalize_envelope_items([{"slug": "c"}]) == [{"slug": "c"}]

    def test_single_item_dict_is_wrapped(self):
        item = {"type": "page", "slug": "d", "title": "D"}
        assert applier.normalize_envelope_items(item) == [item]

    def test_empty_or_meaningless_payload_returns_empty(self):
        assert applier.normalize_envelope_items({}) == []
        assert applier.normalize_envelope_items(None) == []
        assert applier.normalize_envelope_items({"version": 1}) == []

    def test_items_wins_over_cms_posts_when_both_present(self):
        payload = {"items": [{"slug": "x"}], "cms_posts": [{"slug": "y"}]}
        assert applier.normalize_envelope_items(payload) == [{"slug": "x"}]


class TestAllowlist:
    def test_allowlist_is_exactly_the_three_expected_files(self):
        assert applier.PAGE_FILES == (
            "pricing-native.json",
            "pricing-embedded.json",
            "docs-core-subscription-tarif-plans.json",
        )

    def test_allowlist_is_a_strict_subset_of_the_pages_directory(self):
        on_disk = {path.name for path in applier.pages_dir().glob("*.json")}
        # Every allowlisted file exists on disk, but the applier must NOT ship
        # the whole directory (guards against accidental globbing).
        assert set(applier.PAGE_FILES) <= on_disk
        assert set(applier.PAGE_FILES) != on_disk


class TestBundledDocsPage:
    @pytest.fixture()
    def bundled_page(self):
        path = applier.pages_dir() / "docs-core-subscription-tarif-plans.json"
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_uses_the_native_cms_posts_envelope(self, bundled_page):
        assert bundled_page["vbwd_export"] == "cms_posts"
        assert isinstance(bundled_page["cms_posts"], list)

    def test_carries_exactly_one_page(self, bundled_page):
        items = applier.normalize_envelope_items(bundled_page)
        assert len(items) == 1
        assert items[0]["type"] == "page"

    def test_page_identity_and_layout_are_verbatim(self, bundled_page):
        item = applier.normalize_envelope_items(bundled_page)[0]
        assert item["slug"] == "docs-core-subscription/tarif-plans"
        assert item["parent_slug"] == "docs-core-subscription"
        assert item["layout_slug"] == "content-page"

    def test_content_carries_the_live_embed_and_no_legacy_data_plans(
        self, bundled_page
    ):
        item = applier.normalize_envelope_items(bundled_page)[0]
        assert "/embed/widget.js" in item["content_html"]
        assert "data-plans" not in item["content_html"]
