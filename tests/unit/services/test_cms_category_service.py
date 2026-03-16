"""Unit tests for CmsCategoryService."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_category_service import (
    CmsCategoryService,
    CmsCategoryConflictError,
)
from plugins.cms.src.models.cms_category import CmsCategory


def _make_service(categories=None):
    repo = MagicMock()
    cat_store = {str(c.id): c for c in (categories or [])}
    repo.find_by_id.side_effect = lambda cid: cat_store.get(str(cid))
    repo.find_by_slug.side_effect = lambda slug: next(
        (c for c in cat_store.values() if c.slug == slug), None
    )
    repo.save.side_effect = lambda c: cat_store.setdefault(str(c.id), c)
    repo.find_all.return_value = list(cat_store.values())
    return CmsCategoryService(repo), repo


def _category(name="Tech", slug="tech"):
    from uuid import uuid4
    import datetime

    c = CmsCategory()
    c.id = uuid4()
    c.name = name
    c.slug = slug
    c.sort_order = 0
    c.pages = []
    c.children = []
    c.created_at = c.updated_at = datetime.datetime.utcnow()
    return c


class TestCreateCategory:
    def test_create_category_slug_auto_generated(self):
        svc, repo = _make_service()
        svc.create_category({"name": "Web Development"})

        repo.save.assert_called_once()
        saved = repo.save.call_args[0][0]
        assert saved.slug == "web-development"

    def test_create_category_uses_explicit_slug(self):
        svc, repo = _make_service()
        svc.create_category({"name": "Tech", "slug": "tech-stuff"})

        saved = repo.save.call_args[0][0]
        assert saved.slug == "tech-stuff"

    def test_create_category_requires_name(self):
        svc, _ = _make_service()
        with pytest.raises(ValueError, match="name is required"):
            svc.create_category({})


class TestDeleteCategory:
    def test_delete_category_with_pages_raises_conflict(self):
        cat = _category()
        # Simulate having pages
        mock_page = MagicMock()
        cat.pages = [mock_page]
        svc, repo = _make_service(categories=[cat])

        with pytest.raises(CmsCategoryConflictError):
            svc.delete_category(str(cat.id))

        repo.delete.assert_not_called()

    def test_delete_empty_category_succeeds(self):
        cat = _category()
        cat.pages = []
        svc, repo = _make_service(categories=[cat])

        svc.delete_category(str(cat.id))

        repo.delete.assert_called_once_with(str(cat.id))

    def test_delete_nonexistent_raises(self):
        svc, _ = _make_service()
        with pytest.raises(KeyError):
            svc.delete_category("nonexistent-id")
