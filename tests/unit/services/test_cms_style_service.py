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


# ═══════════════════════════════════════════════════════════════════════════
# Sprint 26 — default-style feature
# ═══════════════════════════════════════════════════════════════════════════


def _make_service_with_default(styles=None):
    """Extends _make_service with find_default + save that honours the
    single-default invariant. Tests drive the real service behaviour;
    this mock repo stays simple (no DB constraint)."""
    svc, repo = _make_service(styles)

    def _find_default():
        for s in (styles or []):
            if getattr(s, "is_default", False):
                return s
        return None

    repo.find_default.side_effect = _find_default
    return svc, repo


class TestDefaultFlagBasics:
    def test_new_style_is_not_default_by_default(self):
        svc, _ = _make_service()
        result = svc.create_style({"name": "A", "source_css": "a{}"})
        assert result["is_default"] is False

    def test_set_default_promotes_style(self):
        a = _style(slug="a")
        a.is_default = False
        svc, _ = _make_service_with_default([a])
        result = svc.set_default(str(a.id))
        assert result["is_default"] is True
        assert a.is_default is True

    def test_set_default_demotes_previous_default(self):
        a = _style(slug="a")
        a.is_default = True
        b = _style(slug="b")
        b.is_default = False
        svc, _ = _make_service_with_default([a, b])
        svc.set_default(str(b.id))
        assert a.is_default is False
        assert b.is_default is True

    def test_set_default_on_missing_style_raises_not_found(self):
        svc, _ = _make_service_with_default([])
        with pytest.raises(CmsStyleNotFoundError):
            svc.set_default("00000000-0000-0000-0000-000000000000")

    def test_clear_default_unsets_flag(self):
        a = _style(slug="a")
        a.is_default = True
        svc, _ = _make_service_with_default([a])
        svc.clear_default()
        assert a.is_default is False
        assert svc.get_default_style() is None

    def test_get_default_style_returns_none_when_unset(self):
        svc, _ = _make_service_with_default([_style(slug="a")])
        assert svc.get_default_style() is None

    def test_get_default_style_returns_style_when_set(self):
        a = _style(slug="a")
        a.is_default = True
        svc, _ = _make_service_with_default([a])
        result = svc.get_default_style()
        assert result is not None
        assert result["id"] == str(a.id)

    def test_update_style_is_default_true_demotes_previous(self):
        a = _style(slug="a")
        a.is_default = True
        b = _style(slug="b")
        b.is_default = False
        svc, _ = _make_service_with_default([a, b])
        svc.update_style(str(b.id), {"is_default": True})
        assert a.is_default is False
        assert b.is_default is True

    def test_inactive_default_is_still_returned_by_get_default(self):
        a = _style(slug="a")
        a.is_default = True
        a.is_active = False
        svc, _ = _make_service_with_default([a])
        result = svc.get_default_style()
        assert result is not None
        assert result["is_active"] is False
