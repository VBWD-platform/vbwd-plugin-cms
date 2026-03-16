"""Unit tests for CmsStyleService."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_style_service import (
    CmsStyleService,
    CmsStyleNotFoundError,
    CmsStyleSlugConflictError,
)
from plugins.cms.src.models.cms_style import CmsStyle


def _make_service(styles=None):
    repo = MagicMock()
    store = {s.slug: s for s in (styles or [])}
    id_store = {str(s.id): s for s in (styles or [])}

    repo.find_by_slug.side_effect = lambda slug: store.get(slug)
    repo.find_by_id.side_effect = lambda sid: id_store.get(str(sid))

    def _save(s):
        store[s.slug] = s
        id_store[str(s.id)] = s

    repo.save.side_effect = _save
    repo.find_by_ids.side_effect = lambda ids: [
        id_store[i] for i in ids if i in id_store
    ]
    return CmsStyleService(repo), repo


def _style(slug="my-style", name="My Style", css="body { color: red; }"):
    from uuid import uuid4
    import datetime

    s = CmsStyle()
    s.id = uuid4()
    s.slug = slug
    s.name = name
    s.source_css = css
    s.sort_order = 0
    s.is_active = True
    s.created_at = s.updated_at = datetime.datetime.utcnow()
    return s


class TestCreateStyle:
    def test_create_style_stores_source_css(self):
        svc, repo = _make_service()
        result = svc.create_style(
            {"name": "Footer Style", "source_css": "footer { color: blue; }"}
        )
        assert result["source_css"] == "footer { color: blue; }"
        repo.save.assert_called_once()

    def test_create_style_auto_generates_slug(self):
        svc, _ = _make_service()
        result = svc.create_style({"name": "My Style", "source_css": "p {}"})
        assert result["slug"] == "my-style"

    def test_create_style_uses_explicit_slug(self):
        svc, _ = _make_service()
        result = svc.create_style(
            {"name": "X", "slug": "custom-slug", "source_css": "p {}"}
        )
        assert result["slug"] == "custom-slug"

    def test_create_style_rejects_duplicate_slug(self):
        existing = _style(slug="dupe")
        svc, _ = _make_service(styles=[existing])
        with pytest.raises(CmsStyleSlugConflictError):
            svc.create_style({"name": "Dupe", "slug": "dupe", "source_css": ""})

    def test_create_style_requires_name(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="name"):
            svc.create_style({"source_css": "p {}"})


class TestGetStyleCss:
    def test_get_style_css_returns_source(self):
        s = _style(css="h1 { font-size: 2rem; }")
        svc, _ = _make_service(styles=[s])
        css = svc.get_style_css(str(s.id))
        assert css == "h1 { font-size: 2rem; }"

    def test_get_style_css_raises_not_found(self):
        svc, _ = _make_service()
        with pytest.raises(CmsStyleNotFoundError):
            svc.get_style_css("nonexistent-id")


class TestImportStyle:
    def test_import_style_renames_slug_on_collision(self):
        existing = _style(slug="my-style")
        svc, _ = _make_service(styles=[existing])
        result = svc.import_style(
            {"name": "My Style", "slug": "my-style", "source_css": "a {}"}
        )
        assert result["slug"] == "my-style-2"

    def test_import_style_uses_original_slug_when_no_collision(self):
        svc, _ = _make_service()
        result = svc.import_style(
            {"name": "Fresh", "slug": "fresh-style", "source_css": "a {}"}
        )
        assert result["slug"] == "fresh-style"


class TestBulkDelete:
    def test_bulk_delete_removes_all(self):
        svc, repo = _make_service()
        repo.bulk_delete.return_value = 3
        result = svc.bulk_delete(["id1", "id2", "id3"])
        assert result["deleted"] == 3
        repo.bulk_delete.assert_called_once_with(["id1", "id2", "id3"])
