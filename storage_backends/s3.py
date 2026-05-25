"""S3-compatible storage backend.

Uses boto3 when available. Without boto3, it stores objects in a local directory
named after the bucket, which keeps tests and development dependency-free.
"""
import os
from typing import Optional

from storage_backends.fs import FileSystemStorage
from storage_backends.base import BackendCapabilities


class S3Storage(FileSystemStorage):
    """S3-like backend with optional boto3 support and local fallback."""

    def __init__(self, base_path="./data", bucket="nadb", prefix="", **kwargs):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._boto3_client = None
        try:
            import boto3
            self._boto3_client = boto3.client("s3", **kwargs)
        except Exception:
            self._boto3_client = None
        super().__init__(os.path.join(base_path, bucket), file_mode=kwargs.get("file_mode", 0o600))

    def get_capabilities(self) -> BackendCapabilities:
        caps = super().get_capabilities()
        caps.supports_buffering = False
        caps.write_strategy = "immediate"
        caps.is_distributed = bool(self._boto3_client)
        return caps

    def _object_key(self, relative_path: str) -> str:
        return f"{self.prefix}/{relative_path}".strip("/")

    def write_data(self, relative_path: str, data: bytes) -> bool:
        if self._boto3_client:
            self._boto3_client.put_object(Bucket=self.bucket, Key=self._object_key(relative_path), Body=data)
            return True
        return super().write_data(relative_path, data)

    def read_data(self, relative_path: str) -> Optional[bytes]:
        if self._boto3_client:
            try:
                obj = self._boto3_client.get_object(Bucket=self.bucket, Key=self._object_key(relative_path))
                return obj["Body"].read()
            except Exception:
                return None
        return super().read_data(relative_path)

    def delete_file(self, relative_path: str) -> bool:
        if self._boto3_client:
            self._boto3_client.delete_object(Bucket=self.bucket, Key=self._object_key(relative_path))
            return True
        return super().delete_file(relative_path)

    def file_exists(self, relative_path: str) -> bool:
        if self._boto3_client:
            try:
                self._boto3_client.head_object(Bucket=self.bucket, Key=self._object_key(relative_path))
                return True
            except Exception:
                return False
        return super().file_exists(relative_path)
