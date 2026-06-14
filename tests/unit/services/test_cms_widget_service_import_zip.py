"""Tests for CmsWidgetService.import_widgets_zip — bulk import from a zip.

Mirrors the style-service zip import: the admin can upload a .zip
containing many widget JSON files and get them all imported in one call.
Mode ('replace' / 'copy') applies per entry.
"""
import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.services.cms_widget_service import CmsWidgetService


@pytest.fixture
def repo():
    r = MagicMock()
    r.find_by_slug.return_value = None
    r.save.side_effect = lambda widget: widget
    return r


@pytest.fixture
def menu_repo():
    return MagicMock()


@pytest.fixture
def service(repo, menu_repo):
    return CmsWidgetService(
        widget_repo=repo,
        menu_item_repo=menu_repo,
        image_repo=MagicMock(),
    )


def _zip_of(entries: dict[str, dict]) -> bytes:
    """Build a zip with {filename: widget_dict} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in entries.items():
            zf.writestr(name, json.dumps(payload))
    return buf.getvalue()


def _existing(slug: str):
    from plugins.cms.src.models.cms_widget import CmsWidget

    widget = CmsWidget()
    widget.slug = slug
    widget.name = "Old"
    widget.widget_type = "html"
    widget.content_json = {"html": "<p>old</p>"}
    widget.source_css = "/* old */"
    widget.config = None
    widget.sort_order = 0
    widget.is_active = True
    return widget


class TestImportWidgetsZip:
    def test_zip_with_three_new_widgets_imports_all(self, service, repo):
        raw = _zip_of(
            {
                "a.json": {"slug": "w-a", "name": "A", "widget_type": "html"},
                "b.json": {"slug": "w-b", "name": "B", "widget_type": "html"},
                "c.json": {"slug": "w-c", "name": "C", "widget_type": "html"},
            }
        )

        result = service.import_widgets_zip(raw, mode="replace")

        assert result["imported"] == 3
        assert result["failed"] == 0
        assert len(result["items"]) == 3

    def test_zip_tolerates_nested_paths(self, service, repo):
        """Export format places files under widgets/<slug>.json."""
        raw = _zip_of(
            {
                "widgets/w-a.json": {"slug": "w-a", "name": "A", "widget_type": "html"},
                "widgets/w-b.json": {"slug": "w-b", "name": "B", "widget_type": "html"},
            }
        )

        result = service.import_widgets_zip(raw, mode="copy")
        assert result["imported"] == 2

    def test_replace_mode_upserts_each_entry(self, service, repo):
        existing_map = {"w-a": _existing("w-a")}
        repo.find_by_slug.side_effect = lambda s: existing_map.get(s)

        raw = _zip_of(
            {
                "a.json": {
                    "slug": "w-a",
                    "name": "New A",
                    "widget_type": "html",
                    "source_css": "a{}",
                },
                "b.json": {"slug": "w-b", "name": "B", "widget_type": "html"},
            }
        )

        result = service.import_widgets_zip(raw, mode="replace")

        assert result["imported"] == 2
        # existing row mutated in place, not duplicated
        assert existing_map["w-a"].name == "New A"
        assert existing_map["w-a"].source_css == "a{}"

    def test_non_json_entries_are_skipped(self, service, repo):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "# not a widget")
            zf.writestr("a.json", json.dumps({"slug": "w-a", "name": "A"}))

        result = service.import_widgets_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["skipped"] == 1

    def test_malformed_entry_reported_but_others_succeed(self, service, repo):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("broken.json", "{not json")
            zf.writestr("ok.json", json.dumps({"slug": "w-a", "name": "A"}))

        result = service.import_widgets_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["failed"] == 1
        assert any("broken.json" in e["file"] for e in result["errors"])

    def test_invalid_zip_bytes_raises(self, service):
        with pytest.raises(ValueError, match="zip"):
            service.import_widgets_zip(b"not a zip at all", mode="copy")

    def test_macos_appledouble_metadata_is_ignored(self, service, repo):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("__MACOSX/._a.json", b"\x00\x05\x16\x07binary-apple-double")
            zf.writestr("._b.json", b"\x00\x05\x16\x07binary-apple-double")
            zf.writestr("a.json", json.dumps({"slug": "w-a", "name": "A"}))

        result = service.import_widgets_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["failed"] == 0
        assert result["errors"] == []

    def test_menu_widget_imports_its_tree(self, service, repo, menu_repo):
        raw = _zip_of(
            {
                "menu.json": {
                    "slug": "main-menu",
                    "name": "Main",
                    "widget_type": "menu",
                    "menu_items": [{"label": "Home", "url": "/"}],
                },
            }
        )

        result = service.import_widgets_zip(raw, mode="copy")

        assert result["imported"] == 1
        menu_repo.replace_tree.assert_called_once()
