"""SQLite storage backend that stores values and metadata in one database."""
import os
import sqlite3
import json
from typing import Optional, Dict, Any, List

from storage_backends.base import StorageBackend, BackendCapabilities


class SqliteStorage(StorageBackend):
    """Persistent single-file SQLite backend."""

    def __init__(self, base_path="./data", database_name="nadb.sqlite3", **kwargs):
        os.makedirs(base_path, exist_ok=True)
        self.path = os.path.join(base_path, database_name)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS data (path TEXT PRIMARY KEY, value BLOB NOT NULL)")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                db TEXT NOT NULL,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (db, namespace, key)
            )
        """)
        self.conn.commit()

    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=False,
            supports_native_ttl=False,
            supports_transactions=True,
            supports_metadata=True,
            supports_atomic_writes=True,
            write_strategy="immediate",
            is_persistent=True,
            supports_compression=True,
        )

    def write_data(self, relative_path: str, data: bytes) -> bool:
        self.conn.execute("INSERT OR REPLACE INTO data(path, value) VALUES (?, ?)", (relative_path, data))
        self.conn.commit()
        return True

    def read_data(self, relative_path: str) -> Optional[bytes]:
        row = self.conn.execute("SELECT value FROM data WHERE path = ?", (relative_path,)).fetchone()
        return row[0] if row else None

    def delete_file(self, relative_path: str) -> bool:
        self.conn.execute("DELETE FROM data WHERE path = ?", (relative_path,))
        self.conn.commit()
        return True

    def file_exists(self, relative_path: str) -> bool:
        return self.conn.execute("SELECT 1 FROM data WHERE path = ?", (relative_path,)).fetchone() is not None

    def get_file_size(self, relative_path: str) -> int:
        value = self.read_data(relative_path)
        return len(value) if value else 0

    def get_full_path(self, relative_path: str) -> str:
        return relative_path

    def ensure_directory_exists(self, path: str) -> bool:
        return True

    def set_metadata(self, metadata: Dict[str, Any]) -> bool:
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata(db, namespace, key, payload) VALUES (?, ?, ?, ?)",
            (metadata["db"], metadata["namespace"], metadata["key"], json.dumps(metadata, default=str)),
        )
        self.conn.commit()
        return True

    def get_metadata(self, key: str, db: str, namespace: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT payload FROM metadata WHERE db = ? AND namespace = ? AND key = ?",
            (db, namespace, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def delete_metadata(self, key: str, db: str, namespace: str) -> bool:
        self.conn.execute("DELETE FROM metadata WHERE db = ? AND namespace = ? AND key = ?", (db, namespace, key))
        self.conn.commit()
        return True

    def query_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT payload FROM metadata").fetchall()
        results = []
        for row in rows:
            item = json.loads(row[0])
            if query.get("db") and item.get("db") != query["db"]:
                continue
            if query.get("namespace") and item.get("namespace") != query["namespace"]:
                continue
            tags = query.get("tags") or []
            if tags and not all(tag in item.get("tags", []) for tag in tags):
                continue
            results.append(item)
        return results

    def close_connections(self) -> None:
        self.conn.close()
