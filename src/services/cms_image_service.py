"""CmsImageService — business logic for CMS media gallery."""
import io
import re
import zipfile
import os
from typing import List, Dict, Any, Optional
from plugins.cms.src.repositories.cms_image_repository import CmsImageRepository
from plugins.cms.src.services.file_storage import IFileStorage
from plugins.cms.src.models.cms_image import CmsImage


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s.-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _unique_slug(base: str, repo: CmsImageRepository) -> str:
    slug = base
    counter = 1
    while repo.find_by_slug(slug):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


class CmsImageNotFoundError(Exception):
    """Raised when an image record is not found."""


class CmsImageService:
    """Service for managing CMS images and media files."""

    def __init__(self, repo: CmsImageRepository, storage: IFileStorage) -> None:
        self._repo = repo
        self._storage = storage

    def list_images(
        self,
        page: int = 1,
        per_page: int = 24,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self._repo.find_all(
            page=page, per_page=per_page, sort_by=sort_by,
            sort_dir=sort_dir, search=search,
        )
        result["items"] = [img.to_dict() for img in result["items"]]
        return result

    def upload_image(
        self,
        file_data: bytes,
        filename: str,
        mime_type: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        base_slug = _slugify(os.path.splitext(filename)[0])
        slug = _unique_slug(base_slug, self._repo)

        ext = os.path.splitext(filename)[1].lower() or ".bin"
        relative_path = f"images/{slug}{ext}"

        self._storage.save(file_data, relative_path)
        url_path = self._storage.get_url(relative_path)

        width_px, height_px = self._get_dimensions(file_data, mime_type)

        image = CmsImage()
        image.slug = slug
        image.caption = caption or filename
        image.file_path = relative_path
        image.url_path = url_path
        image.mime_type = mime_type
        image.file_size_bytes = len(file_data)
        image.width_px = width_px
        image.height_px = height_px

        self._repo.save(image)
        return image.to_dict()

    def update_image(self, image_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        image = self._repo.find_by_id(image_id)
        if not image:
            raise CmsImageNotFoundError(f"Image {image_id} not found")

        for field in ("caption", "alt_text", "slug", "og_image_url", "robots", "schema_json"):
            if field in data:
                setattr(image, field, data[field])

        self._repo.save(image)
        return image.to_dict()

    def resize_image(self, image_id: str, width: int, height: int) -> Dict[str, Any]:
        """Resize an image using Pillow. Updates dimensions in DB."""
        image = self._repo.find_by_id(image_id)
        if not image:
            raise CmsImageNotFoundError(f"Image {image_id} not found")

        try:
            from PIL import Image as PILImage

            full_path = os.path.join(
                self._storage.base_path if hasattr(self._storage, "base_path") else "",
                image.file_path,
            )
            with PILImage.open(full_path) as pil_img:
                resized = pil_img.resize((width, height), PILImage.LANCZOS)
                buf = io.BytesIO()
                fmt = pil_img.format or "JPEG"
                resized.save(buf, format=fmt)
                new_data = buf.getvalue()

            self._storage.save(new_data, image.file_path)
            image.width_px = width
            image.height_px = height
            image.file_size_bytes = len(new_data)
            self._repo.save(image)
        except ImportError:
            raise RuntimeError("Pillow is required for image resizing")

        return image.to_dict()

    def delete_image(self, image_id: str) -> None:
        image = self._repo.find_by_id(image_id)
        if not image:
            raise CmsImageNotFoundError(f"Image {image_id} not found")
        self._storage.delete(image.file_path)
        self._repo.delete(image_id)

    def bulk_delete(self, ids: List[str]) -> Dict[str, Any]:
        images = self._repo.bulk_delete(ids)
        for img in images:
            self._storage.delete(img.file_path)
        return {"deleted": len(images)}

    def export_zip(self, ids: List[str]) -> bytes:
        """Return a ZIP archive containing the requested image files."""
        images = self._repo.find_by_ids(ids)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for img in images:
                if self._storage.exists(img.file_path):
                    file_path = img.file_path
                    if hasattr(self._storage, "base_path"):
                        full = os.path.join(self._storage.base_path, file_path)
                        with open(full, "rb") as f:
                            zf.writestr(os.path.basename(file_path), f.read())
                    else:
                        # InMemoryFileStorage
                        data = self._storage._store.get(file_path, b"")
                        zf.writestr(os.path.basename(file_path), data)
        return buf.getvalue()

    # ── private ──────────────────────────────────────────────────────────────

    def _get_dimensions(self, data: bytes, mime_type: str):
        if not mime_type.startswith("image/"):
            return None, None
        try:
            from PIL import Image as PILImage
            with PILImage.open(io.BytesIO(data)) as img:
                return img.width, img.height
        except Exception:
            return None, None
