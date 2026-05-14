"""Tests for CmsStyleService.import_style modes.

The admin import form offers two choices on slug conflict:
  * mode="replace"  → upsert by slug (overwrite name/CSS/sort/active)
  * mode="copy"     → keep existing + save new as "<slug>-2" (default;
                      matches pre-existing behaviour)
"""
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.services.cms_style_service import CmsStyleService


@pytest.fixture
def repo():
    r = MagicMock()
    r.find_by_slug.return_value = None  # no collision by default
    r.save.side_effect = lambda style: style
    return r


@pytest.fixture
def service(repo):
    return CmsStyleService(repo=repo)


def _existing(slug="theme-dark", name="Old Dark"):
    from plugins.cms.src.models.cms_style import CmsStyle

    style = CmsStyle()
    style.slug = slug
    style.name = name
    style.source_css = "/* OLD CSS */"
    style.sort_order = 1
    style.is_active = True
    style.is_default = False
    return style


class TestImportCopyMode:
    def test_no_collision_inserts_as_is(self, service, repo):
        result = service.import_style(
            {"slug": "theme-new", "name": "Theme New", "source_css": "body{}"},
            mode="copy",
        )
        assert result["slug"] == "theme-new"
        repo.save.assert_called_once()

    def test_default_mode_is_copy_and_bumps_slug_on_conflict(self, service, repo):
        # slug "theme-dark" exists once; "theme-dark-2" does not
        def find(slug):
            return _existing("theme-dark") if slug == "theme-dark" else None

        repo.find_by_slug.side_effect = find

        result = service.import_style(
            {"slug": "theme-dark", "name": "Theme Dark", "source_css": "body{}"},
        )
        assert result["slug"] == "theme-dark-2"

    def test_copy_mode_bumps_slug_on_conflict(self, service, repo):
        def find(slug):
            return _existing("theme-dark") if slug == "theme-dark" else None

        repo.find_by_slug.side_effect = find

        result = service.import_style(
            {"slug": "theme-dark", "name": "Theme Dark", "source_css": "body{}"},
            mode="copy",
        )
        assert result["slug"] == "theme-dark-2"


class TestImportReplaceMode:
    def test_no_collision_inserts_at_exact_slug(self, service, repo):
        repo.find_by_slug.return_value = None

        result = service.import_style(
            {"slug": "theme-new", "name": "Theme New", "source_css": "body{}"},
            mode="replace",
        )
        assert result["slug"] == "theme-new"

    def test_collision_overwrites_existing_fields(self, service, repo):
        existing = _existing("theme-dark", name="Old Dark")
        repo.find_by_slug.return_value = existing

        result = service.import_style(
            {
                "slug": "theme-dark",
                "name": "New Dark",
                "source_css": "body{color:red}",
                "sort_order": 5,
                "is_active": False,
            },
            mode="replace",
        )

        assert result["slug"] == "theme-dark"
        assert existing.name == "New Dark"
        assert existing.source_css == "body{color:red}"
        assert existing.sort_order == 5
        assert existing.is_active is False
        repo.save.assert_called_once_with(existing)

    def test_replace_preserves_is_default(self, service, repo):
        """Re-importing the default theme must NOT demote it."""
        existing = _existing("theme-dark")
        existing.is_default = True
        repo.find_by_slug.return_value = existing

        service.import_style(
            {"slug": "theme-dark", "name": "x", "source_css": "", "is_default": False},
            mode="replace",
        )
        assert existing.is_default is True


class TestImportInvalidMode:
    def test_unknown_mode_raises(self, service):
        with pytest.raises(ValueError, match="mode"):
            service.import_style({"slug": "x", "name": "X"}, mode="merge-and-pray")
