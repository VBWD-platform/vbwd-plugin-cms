"""Tests for CmsPageService slug-path composition.

Pages can belong to a category. The stored slug is the FULL URL path a
browser uses to reach the page, e.g. "features/cms-module" when the
page has its own slug "cms-module" and its category's slug is
"features". Flat pages (no category) keep a single-segment slug.

Rules the service enforces on create/update:
  - If the admin's slug input contains "/", take it as-is (strip leading/
    trailing slashes). Admin wins — they've chosen the exact path.
  - Else if the page has a category, prefix the category's slug + "/".
  - Else use the slug as-is (flat page, e.g. "home1", "about").
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


@pytest.fixture
def category_factory():
    """Build a mock category with an id + slug."""
    def _make(slug):
        category = MagicMock()
        category.id = uuid4()
        category.slug = slug
        return category
    return _make


@pytest.fixture
def service(category_factory):
    from plugins.cms.src.services.cms_page_service import CmsPageService

    page_repo = MagicMock()
    page_repo.find_by_slug.return_value = None  # no collision by default
    page_repo.save.side_effect = lambda page: page

    category_repo = MagicMock()
    category_repo.find_by_id.return_value = None

    svc = CmsPageService(repo=page_repo, category_repo=category_repo)
    svc._page_repo_mock = page_repo  # type: ignore[attr-defined]
    svc._category_repo_mock = category_repo  # type: ignore[attr-defined]
    return svc


class TestCreatePageSlugComposition:
    def test_flat_page_without_category_keeps_single_segment_slug(self, service):
        page = service.create_page({"name": "Home", "slug": "home1"})
        assert page["slug"] == "home1"

    def test_page_with_category_prefixes_category_slug(self, service, category_factory):
        category = category_factory("features")
        service._category_repo_mock.find_by_id.return_value = category

        page = service.create_page({
            "name": "CMS Module",
            "slug": "cms-module",
            "category_id": str(category.id),
        })
        assert page["slug"] == "features/cms-module"

    def test_slug_with_slash_overrides_category_prefix(self, service, category_factory):
        category = category_factory("features")
        service._category_repo_mock.find_by_id.return_value = category

        page = service.create_page({
            "name": "Override",
            "slug": "marketing/override",
            "category_id": str(category.id),
        })
        assert page["slug"] == "marketing/override"

    def test_leading_and_trailing_slashes_get_stripped(self, service, category_factory):
        page = service.create_page({
            "name": "x",
            "slug": "/foo/bar/",
        })
        assert page["slug"] == "foo/bar"

    def test_missing_category_row_falls_back_to_flat_slug(self, service):
        service._category_repo_mock.find_by_id.return_value = None

        page = service.create_page({
            "name": "Orphan",
            "slug": "orphan",
            "category_id": str(uuid4()),
        })
        assert page["slug"] == "orphan"


class TestUpdatePageSlugRecomposition:
    def _existing_page(self, slug="home1", category_id=None):
        from plugins.cms.src.models.cms_page import CmsPage

        page = CmsPage()
        page.id = uuid4()
        page.name = "Existing"
        page.slug = slug
        page.category_id = category_id
        return page

    def test_changing_only_slug_recomposes_with_existing_category(self, service, category_factory):
        category = category_factory("features")
        existing = self._existing_page("features/old-slug", category.id)
        service._page_repo_mock.find_by_id.return_value = existing
        service._category_repo_mock.find_by_id.return_value = category

        updated = service.update_page(str(existing.id), {"slug": "new-slug"})
        assert updated["slug"] == "features/new-slug"

    def test_changing_only_category_recomposes_with_new_category(self, service, category_factory):
        old_cat = category_factory("features")
        new_cat = category_factory("products")
        existing = self._existing_page("features/cms-module", old_cat.id)
        service._page_repo_mock.find_by_id.return_value = existing
        # find_by_id returns the NEW category when update_page asks for it.
        service._category_repo_mock.find_by_id.return_value = new_cat

        updated = service.update_page(
            str(existing.id),
            {"category_id": str(new_cat.id)},
        )
        assert updated["slug"] == "products/cms-module"

    def test_removing_category_flattens_slug(self, service):
        existing = self._existing_page("features/cms-module", uuid4())
        service._page_repo_mock.find_by_id.return_value = existing

        updated = service.update_page(
            str(existing.id),
            {"category_id": None},
        )
        assert updated["slug"] == "cms-module"

    def test_explicit_multi_segment_slug_during_update_overrides_category(
        self, service, category_factory,
    ):
        category = category_factory("features")
        existing = self._existing_page("features/old", category.id)
        service._page_repo_mock.find_by_id.return_value = existing
        service._category_repo_mock.find_by_id.return_value = category

        updated = service.update_page(
            str(existing.id),
            {"slug": "custom/deeply/nested"},
        )
        assert updated["slug"] == "custom/deeply/nested"


class TestLookupByFullPath:
    def test_get_page_by_full_path_uses_slug_column_directly(self, service, category_factory):
        from plugins.cms.src.models.cms_page import CmsPage

        page = CmsPage()
        page.id = uuid4()
        page.slug = "features/cms-module"
        page.name = "CMS Module"
        page.is_published = True
        service._page_repo_mock.find_by_slug.return_value = page

        result = service.get_page("features/cms-module", published_only=True)
        service._page_repo_mock.find_by_slug.assert_called_once_with("features/cms-module")
        assert result["slug"] == "features/cms-module"
