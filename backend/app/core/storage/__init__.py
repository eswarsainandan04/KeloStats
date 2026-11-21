from typing import Optional

from app.core.config import settings
from .base import BaseStorageAdapter
from .cloud_storage import CloudStorageAdapter
from .local_storage import LocalStorageAdapter

# Singleton instance cached across the application
_storage_instance: Optional[BaseStorageAdapter] = None


def get_storage(force_mode: Optional[str] = None) -> BaseStorageAdapter:
    """
    Returns the configured storage adapter singleton.
    Driven by STORAGE_MODE in config.py / .env:
      - 'local': Uses LocalStorageAdapter (writes to backend/storage/)
      - 'cloud': Uses CloudStorageAdapter (boto3 client to Supabase / S3)
    """
    global _storage_instance

    if _storage_instance is not None and force_mode is None:
        return _storage_instance

    mode = (force_mode or settings.STORAGE_MODE or "local").lower().strip()

    if mode == "local":
        instance = LocalStorageAdapter(base_dir=settings.LOCAL_STORAGE_DIR)
        print(f"[StorageAdapter] Initialized LocalStorageAdapter at: {settings.LOCAL_STORAGE_DIR}")
    elif mode == "cloud":
        instance = CloudStorageAdapter(
            bucket_name=settings.S3_BUCKET_NAME,
            endpoint_url=settings.S3_ENDPOINT_URL,
            access_key_id=settings.S3_ACCESS_KEY_ID,
            secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
        )
        print(f"[StorageAdapter] Initialized CloudStorageAdapter with bucket: {settings.S3_BUCKET_NAME}")
    else:
        raise ValueError(f"Unknown STORAGE_MODE: '{mode}'. Expected 'local' or 'cloud'.")

    if force_mode is None:
        _storage_instance = instance

    return instance


def reset_storage() -> None:
    """Resets the singleton storage instance (useful for testing or switching modes)."""
    global _storage_instance
    _storage_instance = None


__all__ = [
    "BaseStorageAdapter",
    "LocalStorageAdapter",
    "CloudStorageAdapter",
    "get_storage",
    "reset_storage",
]
