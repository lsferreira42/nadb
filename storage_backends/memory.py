"""In-memory storage backend for tests and ephemeral stores."""
import time
from typing import Optional, Dict, Any, List

from storage_backends.base import StorageBackend, BackendCapabilities


class MemoryStorage(StorageBackend):
    """A non-persistent backend with data and metadata in process memory."""

    def __init__(self, base_path=None, **kwargs):
        self.data: Dict[str, bytes] = {}
        self.metadata: Dict[tuple, Dict[str, Any]] = {}

    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=False,
            supports_native_ttl=False,
            supports_metadata=True,
            supports_atomic_writes=True,
            write_strategy="immediate",
            is_persistent=False,
            supports_compression=True,
        )

    def write_data(self, relative_path: str, data: bytes) -> bool:
        self.data[relative_path] = data
        return True

    def read_data(self, relative_path: str) -> Optional[bytes]:
        return self.data.get(relative_path)

    def delete_file(self, relative_path: str) -> bool:
        self.data.pop(relative_path, None)
        return True

    def file_exists(self, relative_path: str) -> bool:
        return relative_path in self.data

    def get_file_size(self, relative_path: str) -> int:
        return len(self.data.get(relative_path, b""))

    def get_full_path(self, relative_path: str) -> str:
        return relative_path

    def ensure_directory_exists(self, path: str) -> bool:
        return True

    def set_metadata(self, metadata: Dict[str, Any]) -> bool:
        key = (metadata["db"], metadata["namespace"], metadata["key"])
        existing = self.metadata.get(key, {})
        merged = {**existing, **metadata}
        merged.setdefault("created_at", existing.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
        merged["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.metadata[key] = merged
        return True

    def get_metadata(self, key: str, db: str, namespace: str) -> Optional[Dict[str, Any]]:
        item = self.metadata.get((db, namespace, key))
        return dict(item) if item else None

    def delete_metadata(self, key: str, db: str, namespace: str) -> bool:
        self.metadata.pop((db, namespace, key), None)
        return True

    def query_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        for item in self.metadata.values():
            if query.get("db") and item.get("db") != query["db"]:
                continue
            if query.get("namespace") and item.get("namespace") != query["namespace"]:
                continue
            tags = query.get("tags") or []
            if tags and not all(tag in item.get("tags", []) for tag in tags):
                continue
            results.append(dict(item))
        return results
