import os
import shutil
from pathlib import Path
from typing import BinaryIO, List, Optional, Union

from .base import BaseStorageAdapter


class LocalStorageAdapter(BaseStorageAdapter):
    """
    Local filesystem storage adapter.
    Stores all files under backend/storage/ without needing cloud credentials or URLs.
    """

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        if base_dir is None:
            # Default to backend/storage
            backend_root = Path(__file__).resolve().parent.parent.parent.parent
            self.base_dir = (backend_root / "storage").resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

        # Ensure base storage directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _normalize_key(self, key: str) -> str:
        """Converts key to clean POSIX-style relative path without leading slashes."""
        cleaned = str(key).replace("\\", "/").strip().lstrip("/")
        return cleaned

    def _resolve_path(self, key: str) -> Path:
        """
        Safely resolves a storage key into an absolute local file Path.
        Prevents directory traversal attacks (e.g. '../../etc/passwd').
        """
        clean_key = self._normalize_key(key)
        target_path = (self.base_dir / clean_key).resolve()

        # Security check: ensure target_path stays inside base_dir
        if not str(target_path).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected for storage key: {key}")

        return target_path

    def create(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """Creates or writes a file to the local storage directory."""
        target_path = self._resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, str):
            target_path.write_text(data, encoding="utf-8")
        elif isinstance(data, bytes):
            target_path.write_bytes(data)
        elif hasattr(data, "read"):
            if hasattr(data, "seek"):
                try:
                    data.seek(0)
                except Exception:
                    pass
            with open(target_path, "wb") as f:
                shutil.copyfileobj(data, f)
        else:
            raise TypeError(f"Unsupported data type for storage write: {type(data)}")

        return self._normalize_key(key)

    def read(self, key: str) -> bytes:
        """Reads and returns the raw bytes of a local file."""
        target_path = self._resolve_path(key)
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"Local storage file not found: {key}")
        return target_path.read_bytes()

    def update(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """Updates / overwrites an existing local file."""
        return self.create(key=key, data=data, content_type=content_type)

    def delete(self, key: str) -> bool:
        """Deletes a single file from local storage."""
        target_path = self._resolve_path(key)
        if target_path.exists() and target_path.is_file():
            try:
                target_path.unlink()
                return True
            except Exception as err:
                print(f"[LocalStorage] Warning: Failed to delete file {key}: {err}")
                return False
        return True

    def delete_prefix(self, prefix: str) -> int:
        """
        Recursively deletes all files and folders under the specified prefix.
        (e.g., deleting workspace/{user_id}/{project_id}/).
        """
        clean_prefix = self._normalize_key(prefix)
        if not clean_prefix or clean_prefix in (".", "/"):
            raise ValueError("Safety guard: Cannot delete root storage directory using delete_prefix.")

        target_path = self._resolve_path(clean_prefix)
        deleted_count = 0

        if target_path.exists() and target_path.is_dir():
            for root, dirs, files in os.walk(target_path, topdown=False):
                for file in files:
                    try:
                        (Path(root) / file).unlink()
                        deleted_count += 1
                    except Exception:
                        pass
                for dir_name in dirs:
                    try:
                        (Path(root) / dir_name).rmdir()
                    except Exception:
                        pass
            try:
                target_path.rmdir()
            except Exception:
                pass
        elif target_path.exists() and target_path.is_file():
            target_path.unlink()
            deleted_count += 1
        else:
            # Check for partial prefix matching (e.g. 'slides/slide_' matching multiple files)
            parent_dir = target_path.parent
            if parent_dir.exists() and parent_dir.is_dir():
                for item in list(parent_dir.rglob("*")):
                    if item.is_file():
                        rel = item.relative_to(self.base_dir).as_posix()
                        if rel.startswith(clean_prefix):
                            try:
                                item.unlink()
                                deleted_count += 1
                            except Exception:
                                pass

        return deleted_count

    def exists(self, key: str) -> bool:
        """Checks if a local file exists."""
        try:
            target_path = self._resolve_path(key)
            return target_path.exists() and target_path.is_file()
        except ValueError:
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        """Lists all relative file keys matching the prefix."""
        clean_prefix = self._normalize_key(prefix)
        matching_keys: List[str] = []

        if not clean_prefix:
            # List all files in base_dir
            for item in self.base_dir.rglob("*"):
                if item.is_file():
                    matching_keys.append(item.relative_to(self.base_dir).as_posix())
            return sorted(matching_keys)

        target_path = self._resolve_path(clean_prefix)

        if target_path.exists() and target_path.is_dir():
            for item in target_path.rglob("*"):
                if item.is_file():
                    matching_keys.append(item.relative_to(self.base_dir).as_posix())
        elif target_path.exists() and target_path.is_file():
            matching_keys.append(target_path.relative_to(self.base_dir).as_posix())
        else:
            # Handle partial prefix matching (e.g. 'slides/slide_' matching 'slides/slide_01.svg')
            parent_dir = target_path.parent
            if parent_dir.exists() and parent_dir.is_dir():
                for item in parent_dir.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(self.base_dir).as_posix()
                        if rel.startswith(clean_prefix):
                            matching_keys.append(rel)

        return sorted(matching_keys)

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Returns the absolute file URI/path for the local file."""
        target_path = self._resolve_path(key)
        return target_path.as_uri()
