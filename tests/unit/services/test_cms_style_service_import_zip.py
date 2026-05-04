"""Tests for CmsStyleService.import_styles_zip — bulk import from a zip.

The admin can upload a .zip containing many theme JSON files and get
them all imported in one call. Mode ('replace' / 'copy') applies per
entry.
"""
import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.services.cms_style_service import CmsStyleService


@pytest.fixture
def repo():
    r = MagicMock()
    r.find_by_slug.return_value = None
    r.save.side_effect = lambda style: style
    return r


@pytest.fixture
def service(repo):
    return CmsStyleService(repo=repo)


def _zip_of(entries: dict[str, dict]) -> bytes:
    """Build a zip with {filename: style_dict} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in entries.items():
            zf.writestr(name, json.dumps(payload))
    return buf.getvalue()


def _existing(slug: str):
    from plugins.cms.src.models.cms_style import CmsStyle

    style = CmsStyle()
    style.slug = slug
    style.name = "Old"
    style.source_css = "/* old */"
    style.sort_order = 0
    style.is_active = True
    style.is_default = False
    return style


class TestImportStylesZip:
    def test_zip_with_three_new_styles_imports_all(self, service, repo):
        raw = _zip_of({
            "a.json": {"slug": "theme-a", "name": "A", "source_css": ""},
            "b.json": {"slug": "theme-b", "name": "B", "source_css": ""},
            "c.json": {"slug": "theme-c", "name": "C", "source_css": ""},
        })

        result = service.import_styles_zip(raw, mode="replace")

        assert result["imported"] == 3
        assert result["failed"] == 0
        assert len(result["items"]) == 3

    def test_zip_tolerates_nested_paths(self, service, repo):
        """Export format places files under styles/<slug>.json."""
        raw = _zip_of({
            "styles/theme-a.json": {"slug": "theme-a", "name": "A", "source_css": ""},
            "styles/theme-b.json": {"slug": "theme-b", "name": "B", "source_css": ""},
        })

        result = service.import_styles_zip(raw, mode="copy")
        assert result["imported"] == 2

    def test_replace_mode_upserts_each_entry(self, service, repo):
        existing_map = {"theme-a": _existing("theme-a")}
        repo.find_by_slug.side_effect = lambda s: existing_map.get(s)

        raw = _zip_of({
            "a.json": {"slug": "theme-a", "name": "New A", "source_css": "a{}"},
            "b.json": {"slug": "theme-b", "name": "B", "source_css": ""},
        })

        result = service.import_styles_zip(raw, mode="replace")

        assert result["imported"] == 2
        # existing row mutated
        assert existing_map["theme-a"].name == "New A"
        assert existing_map["theme-a"].source_css == "a{}"

    def test_non_json_entries_are_skipped(self, service, repo):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "# not a theme")
            zf.writestr("a.json", json.dumps({"slug": "theme-a", "name": "A"}))

        result = service.import_styles_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["skipped"] == 1

    def test_malformed_entry_reported_but_others_succeed(self, service, repo):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("broken.json", "{not json")
            zf.writestr("ok.json", json.dumps({"slug": "theme-a", "name": "A"}))

        result = service.import_styles_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["failed"] == 1
        assert any("broken.json" in e["file"] for e in result["errors"])

    def test_invalid_zip_bytes_raises(self, service):
        with pytest.raises(ValueError, match="zip"):
            service.import_styles_zip(b"not a zip at all", mode="copy")

    def test_macos_applepdouble_metadata_is_ignored(self, service, repo):
        """macOS `zip` adds __MACOSX/._* AppleDouble files. Ignore them
        silently — they are not skipped (README-style), they are metadata
        artefacts that should not appear in counts at all."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("__MACOSX/._a.json", b"\x00\x05\x16\x07binary-apple-double")
            zf.writestr("._b.json", b"\x00\x05\x16\x07binary-apple-double")
            zf.writestr("a.json", json.dumps({"slug": "theme-a", "name": "A"}))

        result = service.import_styles_zip(buf.getvalue(), mode="copy")
        assert result["imported"] == 1
        assert result["failed"] == 0
        assert result["errors"] == []
