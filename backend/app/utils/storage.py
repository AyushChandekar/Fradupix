"""
Storage Service - MinIO/S3 file storage with local filesystem fallback
"""
import io
import os
import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


class StorageService:
    """MinIO/S3-compatible object storage for invoice files with local fallback."""

    def __init__(self):
        settings = get_settings()
        self.client = None
        self.bucket = settings.MINIO_BUCKET
        self._local_storage = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage"
        )
        self._init_client(settings)

    def _init_client(self, settings):
        """Initialize MinIO client (graceful failure)."""
        try:
            from minio import Minio
            self.client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ROOT_USER,
                secret_key=settings.MINIO_ROOT_PASSWORD,
                secure=settings.MINIO_SECURE,
            )
            # Test connection
            self.client.list_buckets()
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
            logger.info("✅ Connected to MinIO")
        except Exception as e:
            logger.warning(f"⚠️ MinIO unavailable ({e}), using local filesystem storage")
            self.client = None
            os.makedirs(self._local_storage, exist_ok=True)

    def upload_file(
        self, file_bytes: bytes, object_name: str, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload file to storage. Returns object path."""
        if self.client:
            try:
                from minio.error import S3Error
                data = io.BytesIO(file_bytes)
                self.client.put_object(
                    self.bucket, object_name, data,
                    length=len(file_bytes), content_type=content_type,
                )
                return f"{self.bucket}/{object_name}"
            except Exception as e:
                logger.error(f"MinIO upload failed: {e}, falling back to local")

        # Local fallback
        local_path = os.path.join(self._local_storage, object_name)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        return local_path

    def download_file(self, object_name: str) -> bytes:
        """Download file from storage."""
        if object_name.startswith(f"{self.bucket}/"):
            clean_name = object_name[len(f"{self.bucket}/"):]
        else:
            clean_name = object_name

        if self.client:
            try:
                response = self.client.get_object(self.bucket, clean_name)
                data = response.read()
                response.close()
                response.release_conn()
                return data
            except Exception as e:
                logger.error(f"MinIO download failed: {e}")

        # Local fallback — try both original path and clean_name
        for path in [object_name, os.path.join(self._local_storage, clean_name)]:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()

        raise FileNotFoundError(f"File not found: {object_name}")

    def delete_file(self, object_name: str):
        """Delete file from storage."""
        if object_name.startswith(f"{self.bucket}/"):
            clean_name = object_name[len(f"{self.bucket}/"):]
        else:
            clean_name = object_name

        if self.client:
            try:
                self.client.remove_object(self.bucket, clean_name)
                return
            except Exception:
                pass

        for path in [object_name, os.path.join(self._local_storage, clean_name)]:
            if os.path.exists(path):
                os.remove(path)
                return


# Lazy singleton (don't init at import time)
_storage_service = None


def get_storage_service():
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


# For backward compatibility
class _LazyStorage:
    def __getattr__(self, name):
        return getattr(get_storage_service(), name)


storage_service = _LazyStorage()
