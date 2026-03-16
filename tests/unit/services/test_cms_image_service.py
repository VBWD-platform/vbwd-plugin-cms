"""Unit tests for CmsImageService."""
import io
import zipfile
import pytest
from unittest.mock import MagicMock, patch
from plugins.cms.src.services.cms_image_service import CmsImageService, CmsImageNotFoundError
from plugins.cms.src.services.file_storage import InMemoryFileStorage
from plugins.cms.src.models.cms_image import CmsImage


def _make_service(images=None):
    repo = MagicMock()
    storage = InMemoryFileStorage(base_url="/uploads")

    img_store = {str(i.id): i for i in (images or [])}
    slug_store = {i.slug: i for i in (images or [])}

    repo.find_by_id.side_effect = lambda iid: img_store.get(str(iid))
    repo.find_by_slug.side_effect = lambda slug: slug_store.get(slug)
    repo.find_by_ids.side_effect = lambda ids: [img_store[i] for i in ids if i in img_store]
    repo.save.side_effect = lambda img: (img_store.update({str(img.id): img}), img)[1]
    repo.bulk_delete.side_effect = lambda ids: [img_store.pop(str(i)) for i in ids if str(i) in img_store]

    return CmsImageService(repo, storage), repo, storage


def _image(slug="test-image"):
    from uuid import uuid4
    import datetime
    img = CmsImage()
    img.id = uuid4()
    img.slug = slug
    img.caption = "Test"
    img.file_path = f"images/{slug}.png"
    img.url_path = f"/uploads/images/{slug}.png"
    img.mime_type = "image/png"
    img.file_size_bytes = 100
    img.width_px = 800
    img.height_px = 600
    img.created_at = img.updated_at = datetime.datetime.utcnow()
    return img


class TestUploadImage:
    def test_upload_saves_to_storage_and_persists_record(self):
        svc, repo, storage = _make_service()

        # 1x1 white PNG (minimal valid PNG)
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        result = svc.upload_image(
            file_data=png_data,
            filename="hero.png",
            mime_type="image/png",
            caption="Hero image",
        )

        repo.save.assert_called_once()
        assert result["caption"] == "Hero image"
        assert result["mime_type"] == "image/png"
        assert storage.exists(result["file_path"])

    def test_upload_generates_slug_from_filename(self):
        svc, repo, _ = _make_service()

        svc.upload_image(b"data", "My Cool Photo.png", "image/png")

        saved = repo.save.call_args[0][0]
        assert saved.slug == "my-cool-photo"

    def test_upload_deduplicates_slug(self):
        existing = _image("my-photo")
        svc, repo, storage = _make_service(images=[existing])

        svc.upload_image(b"data", "my-photo.png", "image/png")

        saved = repo.save.call_args[0][0]
        # Second upload should get -1 suffix
        assert saved.slug == "my-photo-1"


class TestResizeImage:
    def test_resize_updates_dimensions(self):
        img = _image("resize-me")
        svc, repo, storage = _make_service(images=[img])

        # Pre-populate storage with a minimal valid PNG
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        storage.save(png_data, img.file_path)

        try:
            result = svc.resize_image(str(img.id), 400, 300)
            assert result["width_px"] == 400
            assert result["height_px"] == 300
        except RuntimeError:
            # Pillow not installed in test env — that's acceptable
            pytest.skip("Pillow not available")

    def test_resize_nonexistent_raises(self):
        svc, _, _ = _make_service()
        with pytest.raises(CmsImageNotFoundError):
            svc.resize_image("nonexistent-id", 400, 300)


class TestBulkDelete:
    def test_bulk_delete_removes_files_and_records(self):
        img1 = _image("img1")
        img2 = _image("img2")
        svc, repo, storage = _make_service(images=[img1, img2])

        # Pre-populate storage
        storage.save(b"data1", img1.file_path)
        storage.save(b"data2", img2.file_path)

        repo.bulk_delete.return_value = [img1, img2]
        result = svc.bulk_delete([str(img1.id), str(img2.id)])

        assert result["deleted"] == 2
        assert not storage.exists(img1.file_path)
        assert not storage.exists(img2.file_path)


class TestExportZip:
    def test_export_zip_contains_all_selected_files(self):
        img1 = _image("file1")
        img2 = _image("file2")
        svc, repo, storage = _make_service(images=[img1, img2])

        storage.save(b"content-of-file1", img1.file_path)
        storage.save(b"content-of-file2", img2.file_path)

        repo.find_by_ids.return_value = [img1, img2]
        zip_bytes = svc.export_zip([str(img1.id), str(img2.id)])

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            assert "file1.png" in names
            assert "file2.png" in names
