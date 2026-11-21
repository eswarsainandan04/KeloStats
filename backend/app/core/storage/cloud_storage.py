import io
import mimetypes
from typing import BinaryIO, List, Optional, Union

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import BaseStorageAdapter


class CloudStorageAdapter(BaseStorageAdapter):
    """
    Cloud object storage adapter using Boto3 (compatible with Supabase Storage, AWS S3, MinIO, Cloudflare R2).
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        from app.core.config import settings

        self.bucket_name = bucket_name or settings.S3_BUCKET_NAME or "storage"
        self.endpoint_url = endpoint_url or settings.S3_ENDPOINT_URL
        self.access_key_id = access_key_id or settings.S3_ACCESS_KEY_ID
        self.secret_access_key = secret_access_key or settings.S3_SECRET_ACCESS_KEY
        self.region_name = region_name or settings.S3_REGION or "us-east-1"

        if not self.endpoint_url or not self.access_key_id or not self.secret_access_key:
            raise ValueError(
                "CloudStorageAdapter requires endpoint_url, access_key_id, and secret_access_key. "
                "Check S3_* variables (S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY) in your environment."
            )

        # Production-grade Boto3 configuration with connection pooling and retries
        boto_config = Config(
            signature_version="s3v4",
            max_pool_connections=25,
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30,
        )

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region_name,
            config=boto_config,
        )

    def _normalize_key(self, key: str) -> str:
        """Strips leading slashes and normalizes Windows backslashes."""
        return str(key).replace("\\", "/").strip().lstrip("/")

    def _guess_content_type(self, key: str, fallback: str = "application/octet-stream") -> str:
        """Guesses MIME type from file extension."""
        ctype, _ = mimetypes.guess_type(key)
        if ctype:
            return ctype
        if key.endswith(".svg"):
            return "image/svg+xml; charset=utf-8"
        if key.endswith(".json"):
            return "application/json"
        if key.endswith(".pptx"):
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return fallback

    def create(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """Uploads a file or object to cloud storage."""
        clean_key = self._normalize_key(key)
        ct = content_type or self._guess_content_type(clean_key)

        if isinstance(data, str):
            body: Union[bytes, BinaryIO] = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        elif hasattr(data, "read"):
            if hasattr(data, "seek"):
                try:
                    data.seek(0)
                except Exception:
                    pass
            body = data
        else:
            raise TypeError(f"Unsupported data type for cloud storage write: {type(data)}")

        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=clean_key,
                Body=body,
                ContentType=ct,
            )
            return clean_key
        except ClientError as err:
            raise RuntimeError(f"Failed to upload '{clean_key}' to cloud storage: {err}") from err

    def read(self, key: str) -> bytes:
        """Reads and returns the raw bytes from cloud storage."""
        clean_key = self._normalize_key(key)
        try:
            resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=clean_key)
            return resp["Body"].read()
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Cloud storage file not found: {clean_key}") from err
            raise RuntimeError(f"Error reading '{clean_key}' from cloud storage: {err}") from err

    def update(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """Updates / overwrites an existing cloud storage object."""
        return self.create(key=key, data=data, content_type=content_type)

    def delete(self, key: str) -> bool:
        """Deletes a single file from cloud storage."""
        clean_key = self._normalize_key(key)
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except ClientError as err:
            print(f"[CloudStorage] Warning: Error deleting '{clean_key}': {err}")
            return False

    def delete_prefix(self, prefix: str) -> int:
        """
        Deletes all objects matching the given prefix.
        Handles pagination and batch deletions (up to 1,000 objects per API call).
        """
        clean_prefix = self._normalize_key(prefix)
        if not clean_prefix or clean_prefix in (".", "/"):
            raise ValueError("Safety guard: Cannot delete root storage directory using delete_prefix.")

        deleted_count = 0
        paginator = self.s3_client.get_paginator("list_objects_v2")

        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=clean_prefix):
                contents = page.get("Contents", [])
                if not contents:
                    continue

                delete_batch = [{"Key": obj["Key"]} for obj in contents]
                self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": delete_batch, "Quiet": True},
                )
                deleted_count += len(delete_batch)

            return deleted_count
        except ClientError as err:
            print(f"[CloudStorage] Warning: Error deleting prefix '{clean_prefix}': {err}")
            return deleted_count

    def exists(self, key: str) -> bool:
        """Checks if an object exists in cloud storage via head_object."""
        clean_key = self._normalize_key(key)
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        """Lists all keys matching the prefix."""
        clean_prefix = self._normalize_key(prefix)
        keys: List[str] = []

        paginator = self.s3_client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": self.bucket_name}
        if clean_prefix:
            kwargs["Prefix"] = clean_prefix

        try:
            for page in paginator.paginate(**kwargs):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            return sorted(keys)
        except ClientError as err:
            print(f"[CloudStorage] Warning: Failed to list objects for prefix '{clean_prefix}': {err}")
            return []

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Generates a secure presigned GET URL for downloading the file."""
        clean_key = self._normalize_key(key)
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": clean_key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception:
            # Fallback to direct public URL if presigning fails
            base = self.endpoint_url.rstrip("/")
            return f"{base}/{self.bucket_name}/{clean_key}"
