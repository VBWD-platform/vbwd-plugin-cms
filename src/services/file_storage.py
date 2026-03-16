"""File storage abstraction for CMS media uploads."""
import os
from abc import ABC, abstractmethod


class IFileStorage(ABC):
    """Interface for file storage backends."""

    @abstractmethod
    def save(self, file_data: bytes, relative_path: str) -> str:
        """Save file data to storage. Returns the relative path stored."""

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Delete file at relative_path from storage."""

    @abstractmethod
    def get_url(self, relative_path: str) -> str:
        """Return the public URL for relative_path."""

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        """Return True if the file exists in storage."""

    @abstractmethod
    def read(self, relative_path: str) -> bytes:
        """Return raw bytes of a stored file."""


class LocalFileStorage(IFileStorage):
    """File storage backed by a bind-mounted local directory.

    Files live at: <base_path>/<relative_path>
    URLs served at: <base_url>/<relative_path>

    Production bind mount: /loopai_storage/vbwd/uploads → /app/uploads (container)
    """

    def __init__(self, base_path: str, base_url: str) -> None:
        self.base_path = base_path.rstrip("/")
        self.base_url = base_url.rstrip("/")

    def _full_path(self, relative_path: str) -> str:
        # Prevent path traversal
        relative_path = relative_path.lstrip("/")
        full = os.path.normpath(os.path.join(self.base_path, relative_path))
        if not full.startswith(self.base_path):
            raise ValueError(f"Path traversal attempt: {relative_path}")
        return full

    def save(self, file_data: bytes, relative_path: str) -> str:
        full = self._full_path(relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(file_data)
        return relative_path

    def delete(self, relative_path: str) -> None:
        full = self._full_path(relative_path)
        if os.path.exists(full):
            os.remove(full)

    def get_url(self, relative_path: str) -> str:
        relative_path = relative_path.lstrip("/")
        return f"{self.base_url}/{relative_path}"

    def exists(self, relative_path: str) -> bool:
        return os.path.exists(self._full_path(relative_path))

    def read(self, relative_path: str) -> bytes:
        with open(self._full_path(relative_path), "rb") as f:
            return f.read()


class InMemoryFileStorage(IFileStorage):
    """In-memory storage for unit tests — no disk I/O."""

    def __init__(self, base_url: str = "/uploads") -> None:
        self.base_url = base_url.rstrip("/")
        self._store: dict[str, bytes] = {}

    def save(self, file_data: bytes, relative_path: str) -> str:
        self._store[relative_path] = file_data
        return relative_path

    def delete(self, relative_path: str) -> None:
        self._store.pop(relative_path, None)

    def get_url(self, relative_path: str) -> str:
        relative_path = relative_path.lstrip("/")
        return f"{self.base_url}/{relative_path}"

    def exists(self, relative_path: str) -> bool:
        return relative_path in self._store

    def read(self, relative_path: str) -> bytes:
        if relative_path not in self._store:
            raise FileNotFoundError(relative_path)
        return self._store[relative_path]
