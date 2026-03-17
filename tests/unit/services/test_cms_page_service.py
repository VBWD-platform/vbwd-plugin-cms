"""Unit tests for CmsPageService."""
import pytest
import json
from unittest.mock import MagicMock
from plugins.cms.src.services.cms_page_service import (
    CmsPageService,
    CmsPageNotFoundError,
    CmsPageSlugConflictError,
)
from plugins.cms.src.models.cms_page import CmsPage
from plugins.cms.src.models.cms_category import CmsCategory


def _make_service(pages=None, categories=None):
    """Build a CmsPageService with mock repositories."""
    page_repo = MagicMock()
    cat_repo = MagicMock()

    page_store = {p.slug: p for p in (pages or [])}
    page_id_store = {str(p.id): p for p in (pages or [])}

    page_repo.find_by_slug.side_effect = lambda slug: page_store.get(slug)
    page_repo.find_by_id.side_effect = lambda pid: page_id_store.get(str(pid))

    # Flush/add simulate persistence
    def _save(p):
        page_store[p.slug] = p
        page_id_store[str(p.id)] = p

    page_repo.save.side_effect = _save
    page_repo.find_by_ids.side_effect = lambda ids: [
        page_id_store[i] for i in ids if i in page_id_store
    ]

    return CmsPageService(page_repo, cat_repo), page_repo, cat_repo


def _page(slug="my-page", published=True, name="My Page"):
    from uuid import uuid4

    p = CmsPage()
    p.id = uuid4()
    p.slug = slug
    p.name = name
    p.language = "en"
    p.content_json = {"type": "doc", "content": []}
    p.is_published = published
    p.sort_order = 0
    p.robots = "index,follow"
    p.created_at = p.updated_at = __import__("datetime").datetime.utcnow()
    return p


class TestGetPage:
    def test_get_page_by_slug_returns_dto(self):
        page = _page("hello-world", published=True)
        svc, _, _ = _make_service(pages=[page])

        result = svc.get_page("hello-world")

        assert result["slug"] == "hello-world"
        assert result["is_published"] is True

    def test_get_unpublished_page_raises_not_found(self):
        page = _page("draft-page", published=False)
        svc, _, _ = _make_service(pages=[page])

        with pytest.raises(CmsPageNotFoundError):
            svc.get_page("draft-page", published_only=True)

    def test_get_unpublished_page_admin_mode_returns_dto(self):
        page = _page("draft-page", published=False)
        svc, _, _ = _make_service(pages=[page])

        result = svc.get_page("draft-page", published_only=False)
        assert result["is_published"] is False

    def test_get_nonexistent_page_raises_not_found(self):
        svc, _, _ = _make_service()
        with pytest.raises(CmsPageNotFoundError):
            svc.get_page("nonexistent")


class TestCreatePage:
    def test_create_page_validates_slug_uniqueness(self):
        existing = _page("about-us")
        svc, repo, _ = _make_service(pages=[existing])

        with pytest.raises(CmsPageSlugConflictError):
            svc.create_page({"name": "About Us", "slug": "about-us"})

    def test_create_page_auto_generates_slug_from_name(self):
        svc, repo, _ = _make_service()

        svc.create_page({"name": "My Cool Page"})

        repo.save.assert_called_once()
        saved = repo.save.call_args[0][0]
        assert saved.slug == "my-cool-page"

    def test_create_page_requires_name(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="name is required"):
            svc.create_page({})


class TestBulkActions:
    def test_bulk_publish_updates_all_ids(self):
        svc, repo, _ = _make_service()
        repo.bulk_publish.return_value = 3

        result = svc.bulk_action(["id1", "id2", "id3"], "publish")

        repo.bulk_publish.assert_called_once_with(["id1", "id2", "id3"], True)
        assert result["affected"] == 3

    def test_bulk_unpublish(self):
        svc, repo, _ = _make_service()
        repo.bulk_publish.return_value = 2

        result = svc.bulk_action(["id1", "id2"], "unpublish")

        repo.bulk_publish.assert_called_once_with(["id1", "id2"], False)
        assert result["affected"] == 2

    def test_bulk_delete(self):
        svc, repo, _ = _make_service()
        repo.bulk_delete.return_value = 1

        result = svc.bulk_action(["id1"], "delete")

        repo.bulk_delete.assert_called_once_with(["id1"])
        assert result["affected"] == 1

    def test_bulk_unknown_action_raises(self):
        svc, _, _ = _make_service()
        with pytest.raises(ValueError, match="Unknown bulk action"):
            svc.bulk_action(["id1"], "unknown-action")


class TestExport:
    def test_export_json_includes_all_fields(self):
        from uuid import uuid4

        page = _page("export-me", published=True)
        page.meta_title = "Export Test"
        svc, repo, _ = _make_service(pages=[page])
        repo.find_by_ids.return_value = [page]

        raw = svc.export_pages([str(page.id)], fmt="json")
        data = json.loads(raw)

        assert len(data) == 1
        assert data[0]["slug"] == "export-me"
        assert data[0]["meta_title"] == "Export Test"
        assert "content_json" in data[0]

    def test_export_base64_encodes_payload(self):
        import base64

        page = _page("b64-page")
        svc, repo, _ = _make_service(pages=[page])
        repo.find_by_ids.return_value = [page]

        raw = svc.export_pages([str(page.id)], fmt="json_base64")
        decoded = base64.b64decode(raw)
        data = json.loads(decoded)

        assert data[0]["slug"] == "b64-page"
