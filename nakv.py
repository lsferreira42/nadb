""" Simple key-value store with disk persistence and buffer management."""
import os
import json
import sqlite3
import threading
import time
import zlib
import io
import statistics
import weakref
import hashlib
import base64
import tarfile
from hashlib import blake2b
from collections import defaultdict
from datetime import datetime, timedelta
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Union, Set, Callable, Iterable, Iterator

from storage_backends import StorageFactory
from _version import __version__

DEFAULT_ENCODING = "utf-8"
DEFAULT_NAMESPACE = "default"
DEFAULT_BUFFER_SIZE_MB = 1
MAX_KEY_LENGTH = 1024
MAX_NAMESPACE_LENGTH = 256
MAX_DB_LENGTH = 256
MAX_TAG_LENGTH = 256
ValueInput = Union[str, bytes, bytearray, memoryview]
ReturnType = str

# Try to import advanced features, fall back gracefully if not available
try:
    from logging_config import LoggingConfig
    LoggingConfig.setup_logging()
    LOGGING_AVAILABLE = True
except ImportError:
    LoggingConfig = None
    LOGGING_AVAILABLE = False

try:
    from transaction import TransactionManager
    TRANSACTIONS_AVAILABLE = True
except ImportError:
    TransactionManager = None
    TRANSACTIONS_AVAILABLE = False

try:
    from backup_manager import BackupManager
    BACKUP_AVAILABLE = True
except ImportError:
    BackupManager = None
    BACKUP_AVAILABLE = False

try:
    from index_manager import IndexManager, QueryOperator
    INDEXING_AVAILABLE = True
except ImportError:
    IndexManager = None
    QueryOperator = None
    INDEXING_AVAILABLE = False

# Constants for compression
COMPRESS_MIN_SIZE = 1024  # Only compress files larger than 1KB
COMPRESS_LEVEL = 6  # Medium compression (range is 0-9)

# Thread local storage for SQLite connections
thread_local = threading.local()

class KeyValueMetadata:
    """Metadata controller for a kv store"""
    def __init__(self, sqlite_db: str, data_folder_path: str):
        self.sqlite_db = os.path.join(data_folder_path, sqlite_db)
        if not os.path.exists(self.sqlite_db):
            self._create_database()
        self._migrate_database()
        
        # Use RLock to allow re-entrant lock acquisition (safer for recursive calls)
        self.connection_lock = threading.RLock()
    
    def _get_db_connection(self):
        """Get a thread-local database connection."""
        if not hasattr(thread_local, 'db_connections'):
            thread_local.db_connections = {}
            
        thread_id = threading.get_ident()
        if thread_id not in thread_local.db_connections:
            # Create a new connection for this thread
            conn = sqlite3.connect(self.sqlite_db)
            # Enable foreign key constraints
            conn.execute("PRAGMA foreign_keys = ON")
            thread_local.db_connections[thread_id] = conn
            
        return thread_local.db_connections[thread_id]
        
    def _create_database(self):
        """Creates the SQLite database and metadata table."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            script_dir = os.getcwd()
            
        # Ensure parent directory for database exists
        os.makedirs(os.path.dirname(self.sqlite_db), exist_ok=True)
            
        # Try multiple possible locations for the SQL file
        sql_locations = [
            os.path.join(script_dir, 'sql'),  # Standard location
            os.path.join(os.getcwd(), 'sql'),  # Current working directory
            os.path.dirname(self.sqlite_db)    # Metadata DB location
        ]
        
        sql_file_path = None
        for sql_folder in sql_locations:
            potential_path = os.path.join(sql_folder, 'metadata.sql')
            if os.path.exists(potential_path):
                sql_file_path = potential_path
                break
                
        if not sql_file_path:
            # If SQL file not found, use hardcoded schema as fallback
            schema = """
            CREATE TABLE metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                key TEXT NOT NULL,
                db TEXT NOT NULL,
                namespace TEXT NOT NULL,
                created_at DATETIME DEFAULT NULL,
                last_updated DATETIME DEFAULT NULL,
                last_accessed DATETIME DEFAULT NULL,
                size INTEGER DEFAULT NULL,
                logical_size INTEGER DEFAULT NULL,
                stored_size INTEGER DEFAULT NULL,
                value_type TEXT DEFAULT 'bytes',
                encoding TEXT DEFAULT NULL,
                content_type TEXT DEFAULT NULL,
                checksum TEXT DEFAULT NULL,
                encrypted INTEGER DEFAULT 0,
                ttl INTEGER DEFAULT NULL,
                expires_at DATETIME DEFAULT NULL,
                UNIQUE (path, key, db, namespace)
            );

            -- Tags Table
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT NOT NULL UNIQUE
            );

            -- Linking Table
            CREATE TABLE metadata_tags (
                metadata_id INTEGER,
                tag_id INTEGER,
                PRIMARY KEY (metadata_id, tag_id),
                FOREIGN KEY (metadata_id) REFERENCES metadata(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            """
        else:
            # Read schema from file
            with open(sql_file_path, 'r') as f:
                schema = f.read()
            
        # Use a direct connection for database creation
        with sqlite3.connect(self.sqlite_db) as conn:
            conn.executescript(schema)

    def _migrate_database(self):
        """Apply additive metadata schema migrations for existing stores."""
        columns = {
            "logical_size": "INTEGER DEFAULT NULL",
            "stored_size": "INTEGER DEFAULT NULL",
            "value_type": "TEXT DEFAULT 'bytes'",
            "encoding": "TEXT DEFAULT NULL",
            "content_type": "TEXT DEFAULT NULL",
            "checksum": "TEXT DEFAULT NULL",
            "encrypted": "INTEGER DEFAULT 0",
            "expires_at": "DATETIME DEFAULT NULL",
        }
        with sqlite3.connect(self.sqlite_db) as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(metadata)")}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE metadata ADD COLUMN {column} {definition}")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            current = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if current is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (2,))
            elif current[0] < 2:
                conn.execute("UPDATE schema_version SET version = ?", (2,))
            conn.commit()

    def set_metadata(self, metadata: dict):
        # Check if the record already exists
        fetch_sql = '''SELECT id, created_at FROM metadata WHERE path = ? AND key = ? AND db = ? AND namespace = ?'''
        fetch_params = (metadata.get("path"), metadata.get("key"), metadata.get("db"), metadata.get("namespace"))

        try:
            db = self._get_db_connection()
            with self.connection_lock:
                cur = db.execute(fetch_sql, fetch_params)
                row = cur.fetchone()
                existing_id, existing_created_at = (row[0], row[1]) if row else (None, None)

                if existing_created_at:
                    # Record exists; perform an update
                    sql = '''UPDATE metadata SET
                                last_updated = ?,
                                last_accessed = ?,
                                size = ?,
                                logical_size = ?,
                                stored_size = ?,
                                value_type = ?,
                                encoding = ?,
                                content_type = ?,
                                checksum = ?,
                                encrypted = ?,
                                ttl = ?,
                                expires_at = ?
                            WHERE path = ? AND key = ? AND db = ? AND namespace = ?'''
                    now = datetime.now().isoformat()
                    params = (
                        now,
                        now,
                        metadata.get("size"),
                        metadata.get("logical_size", metadata.get("size")),
                        metadata.get("stored_size", metadata.get("size")),
                        metadata.get("value_type", "bytes"),
                        metadata.get("encoding"),
                        metadata.get("content_type"),
                        metadata.get("checksum"),
                        int(bool(metadata.get("encrypted", False))),
                        metadata.get("ttl"),
                        metadata.get("expires_at"),
                        metadata.get("path"),
                        metadata.get("key"),
                        metadata.get("db"),
                        metadata.get("namespace")
                    )
                    db.execute(sql, params)
                    metadata_id = existing_id
                else:
                    # Record doesn't exist; perform an insert
                    sql = '''INSERT INTO metadata (
                                path,
                                key,
                                db,
                                namespace,
                                created_at,
                                last_updated,
                                last_accessed,
                                size,
                                logical_size,
                                stored_size,
                                value_type,
                                encoding,
                                content_type,
                                checksum,
                                encrypted,
                                ttl,
                                expires_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''
                    now = datetime.now().isoformat()
                    params = (
                        metadata.get("path"),
                        metadata.get("key"),
                        metadata.get("db"),
                        metadata.get("namespace"),
                        now,
                        now,
                        now,
                        metadata.get("size"),
                        metadata.get("logical_size", metadata.get("size")),
                        metadata.get("stored_size", metadata.get("size")),
                        metadata.get("value_type", "bytes"),
                        metadata.get("encoding"),
                        metadata.get("content_type"),
                        metadata.get("checksum"),
                        int(bool(metadata.get("encrypted", False))),
                        metadata.get("ttl"),
                        metadata.get("expires_at")
                    )
                    cursor = db.execute(sql, params)
                    metadata_id = cursor.lastrowid
                    
                # Process tags if provided
                if "tags" in metadata and metadata["tags"]:
                    self.set_tags(metadata_id, metadata["tags"])
                    
                # Commit the transaction
                db.commit()
        except sqlite3.Error as e:
            logging.error(f"SQLite error in set_metadata: {e}")
            raise

    def set_tags(self, metadata_id: int, tags: list):
        """Set tags for a metadata entry.
        
        Args:
            metadata_id: The ID of the metadata entry
            tags: List of tag names
        """
        try:
            # Ensure tag uniqueness to prevent SQLite UNIQUE constraint violations
            unique_tags = list(set(tags)) if tags else []
            
            db = self._get_db_connection()
            with self.connection_lock:
                # First, remove any existing tags for this metadata
                db.execute("DELETE FROM metadata_tags WHERE metadata_id = ?", (metadata_id,))
                
                # Add each tag
                for tag_name in unique_tags:
                    # Check if tag exists
                    cursor = db.execute("SELECT id FROM tags WHERE tag_name = ?", (tag_name,))
                    row = cursor.fetchone()
                    
                    if row:
                        tag_id = row[0]
                    else:
                        # Create new tag
                        cursor = db.execute("INSERT INTO tags (tag_name) VALUES (?)", (tag_name,))
                        tag_id = cursor.lastrowid
                    
                    # Link tag to metadata
                    db.execute(
                        "INSERT INTO metadata_tags (metadata_id, tag_id) VALUES (?, ?)",
                        (metadata_id, tag_id)
                    )
                
                # Commit the transaction
                db.commit()
        except sqlite3.Error as e:
            logging.error(f"SQLite error in set_tags: {e}")
            raise

    def get_metadata(self, key: str, db: str, namespace: str) -> dict:
        """Returns the metadata for the specified key.
        
        Args:
            key: The key to get metadata for
            db: The database name
            namespace: The namespace
            
        Returns:
            Dictionary containing metadata and tags
        """
        sql = """
            SELECT 
                m.id, m.path, m.key, m.db, m.namespace, 
                m.created_at, m.last_updated, m.last_accessed,
                m.size, m.logical_size, m.stored_size, m.value_type,
                m.encoding, m.content_type, m.checksum, m.encrypted, m.ttl,
                m.expires_at, GROUP_CONCAT(t.tag_name) as tags
            FROM metadata m
            LEFT JOIN metadata_tags mt ON m.id = mt.metadata_id
            LEFT JOIN tags t ON mt.tag_id = t.id
            WHERE m.key = ? AND m.db = ? AND m.namespace = ?
            GROUP BY m.id
        """
        
        try:
            db_conn = self._get_db_connection()
            with self.connection_lock:
                cursor = db_conn.execute(sql, (key, db, namespace))
                row = cursor.fetchone()
                
                if not row:
                    return None
                    
                # Update last accessed time
                db_conn.execute(
                    "UPDATE metadata SET last_accessed = ? WHERE id = ?",
                    (datetime.now().isoformat(), row[0])
                )
                db_conn.commit()
            
            # Parse tags
            tags = row[18].split(',') if row[18] else []
            
            return {
                "id": row[0],
                "path": row[1],
                "key": row[2],
                "db": row[3],
                "namespace": row[4],
                "created_at": row[5],
                "last_updated": row[6],
                "last_accessed": row[7],
                "size": row[8],
                "logical_size": row[9],
                "stored_size": row[10],
                "value_type": row[11],
                "encoding": row[12],
                "content_type": row[13],
                "checksum": row[14],
                "encrypted": bool(row[15]),
                "ttl": row[16],
                "expires_at": row[17],
                "tags": tags
            }
        except sqlite3.Error as e:
            logging.error(f"SQLite error in get_metadata: {e}")
            raise
    
    def delete_metadata(self, key: str, db: str, namespace: str):
        """Deletes the metadata for the specified key."""
        try:
            db_conn = self._get_db_connection()
            with self.connection_lock:
                db_conn.execute(
                    "DELETE FROM metadata WHERE key = ? AND db = ? AND namespace = ?",
                    (key, db, namespace)
                )
                db_conn.commit()
        except sqlite3.Error as e:
            logging.error(f"SQLite error in delete_metadata: {e}")
            raise

    @staticmethod
    def _escape_like_pattern(pattern: str) -> str:
        """Escape special characters in SQL LIKE patterns to prevent injection."""
        # Escape special LIKE characters: % _ and the escape character \
        escaped = pattern.replace('\\', '\\\\')  # Escape backslash first
        escaped = escaped.replace('%', '\\%')
        escaped = escaped.replace('_', '\\_')
        return escaped

    def query_metadata(self, query: dict) -> list:
        """Queries the metadata based on provided criteria.

        Args:
            query: Dictionary containing query parameters:
                - key: Key name pattern (supports SQL LIKE)
                - db: Database name
                - namespace: Namespace
                - tags: List of tags (all must match)
                - min_size/max_size: Size constraints
                - created_before/created_after: Creation time constraints
                - updated_before/updated_after: Update time constraints
                - accessed_before/accessed_after: Access time constraints

        Returns:
            List of metadata dictionaries matching the criteria
        """
        conditions = []
        params = []

        # Basic metadata filters
        if 'key' in query:
            # Sanitize the key pattern to prevent SQL injection via LIKE
            safe_key = self._escape_like_pattern(query['key'])
            conditions.append("m.key LIKE ? ESCAPE '\\'")
            params.append(f"%{safe_key}%")
            
        if 'db' in query:
            conditions.append("m.db = ?")
            params.append(query['db'])
            
        if 'namespace' in query:
            conditions.append("m.namespace = ?")
            params.append(query['namespace'])
            
        # Size filters
        if 'min_size' in query:
            conditions.append("m.size >= ?")
            params.append(query['min_size'])
            
        if 'max_size' in query:
            conditions.append("m.size <= ?")
            params.append(query['max_size'])
            
        # Time filters
        if 'created_before' in query:
            conditions.append("m.created_at <= ?")
            params.append(query['created_before'])
            
        if 'created_after' in query:
            conditions.append("m.created_at >= ?")
            params.append(query['created_after'])
            
        if 'updated_before' in query:
            conditions.append("m.last_updated <= ?")
            params.append(query['updated_before'])
            
        if 'updated_after' in query:
            conditions.append("m.last_updated >= ?")
            params.append(query['updated_after'])
            
        if 'accessed_before' in query:
            conditions.append("m.last_accessed <= ?")
            params.append(query['accessed_before'])
            
        if 'accessed_after' in query:
            conditions.append("m.last_accessed >= ?")
            params.append(query['accessed_after'])
        
        # Tag filters
        if 'tags' in query and query['tags']:
            tag_conditions = []
            for tag in query['tags']:
                tag_subquery = """
                    m.id IN (
                        SELECT metadata_id 
                        FROM metadata_tags mt 
                        JOIN tags t ON mt.tag_id = t.id 
                        WHERE t.tag_name = ?
                    )
                """
                tag_conditions.append(tag_subquery)
                params.append(tag)
                
            conditions.append(f"({' AND '.join(tag_conditions)})")
        
        # Build the SQL query
        sql = """
            SELECT 
                m.id, m.path, m.key, m.db, m.namespace, 
                m.created_at, m.last_updated, m.last_accessed,
                m.size, m.logical_size, m.stored_size, m.value_type,
                m.encoding, m.content_type, m.checksum, m.encrypted, m.ttl,
                m.expires_at, GROUP_CONCAT(t.tag_name) as tags
            FROM metadata m
            LEFT JOIN metadata_tags mt ON m.id = mt.metadata_id
            LEFT JOIN tags t ON mt.tag_id = t.id
        """
        
        if conditions:
            sql += f" WHERE {' AND '.join(conditions)}"
            
        sql += " GROUP BY m.id"
        
        # Execute query
        try:
            db_conn = self._get_db_connection()
            with self.connection_lock:
                cursor = db_conn.execute(sql, params)
                results = []
                
                for row in cursor.fetchall():
                    tags = row[18].split(',') if row[18] else []
                    
                    result = {
                        "id": row[0],
                        "path": row[1],
                        "key": row[2],
                        "db": row[3],
                        "namespace": row[4],
                        "created_at": row[5],
                        "last_updated": row[6],
                        "last_accessed": row[7],
                        "size": row[8],
                        "logical_size": row[9],
                        "stored_size": row[10],
                        "value_type": row[11],
                        "encoding": row[12],
                        "content_type": row[13],
                        "checksum": row[14],
                        "encrypted": bool(row[15]),
                        "ttl": row[16],
                        "expires_at": row[17],
                        "tags": tags
                    }
                    results.append(result)
            
            return results
        except sqlite3.Error as e:
            logging.error(f"SQLite error in query_metadata: {e}")
            raise
        
    def cleanup_expired(self):
        """Remove entries that have expired based on TTL."""
        now = datetime.now().isoformat()
        
        # Find expired entries
        sql = """
            SELECT id, path, key, db, namespace
            FROM metadata
            WHERE (
                expires_at IS NOT NULL AND expires_at < ?
            ) OR (
                expires_at IS NULL
                AND ttl IS NOT NULL
                AND last_updated IS NOT NULL
                AND datetime(last_updated, '+' || ttl || ' seconds') < ?
            )
        """
        
        try:
            db_conn = self._get_db_connection()
            expired_items = []
            
            with self.connection_lock:
                cursor = db_conn.execute(sql, (now, now))
                expired_entries = cursor.fetchall()
                
                # Delete expired entries
                if expired_entries:
                    for entry in expired_entries:
                        # Return info about deleted entries
                        item_info = {
                            "id": entry[0],
                            "path": entry[1],
                            "key": entry[2], 
                            "db": entry[3],
                            "namespace": entry[4]
                        }
                        expired_items.append(item_info)
                        
                        # Delete the entry
                        db_conn.execute("DELETE FROM metadata WHERE id = ?", (entry[0],))
                    
                    # Commit the transaction
                    db_conn.commit()
            
            return expired_items
        except sqlite3.Error as e:
            logging.error(f"SQLite error in cleanup_expired: {e}")
            raise

    def close_connections(self):
        """Close all database connections."""
        if hasattr(thread_local, 'db_connections'):
            with self.connection_lock:
                for conn in thread_local.db_connections.values():
                    try:
                        conn.close()
                    except Exception as e:
                        logging.error(f"Error closing database connection: {e}")
                thread_local.db_connections.clear()

    def query_tags(self, db: str, namespace: str) -> dict:
        """
        Get all unique tags used in this database/namespace with counts.
        
        Args:
            db: Database name
            namespace: Namespace
            
        Returns:
            Dictionary of tag -> count
        """
        try:
            # Query all entries with their tags for this db and namespace
            entries = self.query_metadata({
                "db": db,
                "namespace": namespace
            })
            
            # Count tag occurrences
            tag_counts = defaultdict(int)
            for entry in entries:
                tags = entry.get("tags", [])
                for tag in tags:
                    tag_counts[tag] += 1
                    
            return dict(tag_counts)
        except sqlite3.Error as e:
            logging.error(f"SQLite error in query_tags: {e}")
            return {}


class KeyValueSync:
    """Key value store synchronization."""

    def __init__(self, flush_interval_seconds: int):
        self.flush_interval = flush_interval_seconds
        self.stores = []
        self.is_running = False
        self.thread = None
        self.last_ttl_cleanup = datetime.now()
        self.ttl_cleanup_interval = 60  # Check for expired items every minute

    def flush_and_sleep(self):
        """Flushes all stores and sleeps for a period of time."""
        for store in self.stores:
            store.flush_if_needed()
            
        # Check if we need to cleanup expired items
        if (datetime.now() - self.last_ttl_cleanup).total_seconds() >= self.ttl_cleanup_interval:
            self._cleanup_expired_entries()
            self.last_ttl_cleanup = datetime.now()
            
        time.sleep(self.flush_interval)

    def register_store(self, store):
        """Registers a store for synchronization."""
        self.stores.append(store)

    def start(self):
        """Starts synchronization in a separate thread."""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def _run(self):
        """Thread function for synchronization."""
        while self.is_running:
            try:
                self.flush_and_sleep()
            except Exception as e:
                logging.error(f"Error in sync thread: {e}")
                time.sleep(1)  # Prevent tight loop in case of recurring errors
                
    def _cleanup_expired_entries(self):
        """Cleanup expired entries in all stores."""
        total_expired = 0
        for store in self.stores:
            try:
                expired_items = store.cleanup_expired()
                if expired_items:
                    total_expired += len(expired_items)
            except Exception as e:
                logging.error(f"Error cleaning up expired entries: {e}")
                
        if total_expired > 0:
            logging.info(f"Removed {total_expired} expired entries")

    def status(self):
        """Returns status information about the synchronization process."""
        return {
            "is_running": self.is_running,
            "flush_interval": self.flush_interval,
            "registered_stores": len(self.stores),
            "last_ttl_cleanup": self.last_ttl_cleanup.isoformat(),
            "ttl_cleanup_interval": self.ttl_cleanup_interval
        }

    def sync_exit(self):
        """Exits synchronization process."""
        if not self.is_running:
            return

        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2 * self.flush_interval)
            if self.thread.is_alive():
                logging.warning("Sync thread did not exit gracefully")


class PerformanceMetrics:
    """Collect and report performance metrics for the key-value store."""
    
    def __init__(self):
        self.operation_times = defaultdict(list)
        self.operation_counts = defaultdict(int)
        self.bytes_read = 0
        self.bytes_written = 0
        self.lock = threading.Lock()
        self.start_time = datetime.now()
        
    def record_operation(self, operation_name, duration_ms, size_bytes=0):
        """Record timing for an operation."""
        with self.lock:
            self.operation_times[operation_name].append(duration_ms)
            self.operation_counts[operation_name] += 1
            
            if operation_name == 'read':
                self.bytes_read += size_bytes
            elif operation_name == 'write':
                self.bytes_written += size_bytes
                
    def get_metrics(self):
        """Return current metrics."""
        with self.lock:
            metrics = {
                'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
                'operations': {},
                'bytes_read': self.bytes_read,
                'bytes_written': self.bytes_written,
                'compression_ratio': 0 if self.bytes_written == 0 else self.bytes_read / self.bytes_written
            }
            
            # Calculate stats for each operation
            for op_name, times in self.operation_times.items():
                if not times:
                    continue
                    
                metrics['operations'][op_name] = {
                    'count': self.operation_counts[op_name],
                    'avg_ms': statistics.mean(times) if times else 0,
                    'min_ms': min(times) if times else 0,
                    'max_ms': max(times) if times else 0,
                    'p95_ms': statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max(times) if times else 0
                }
                
            return metrics


@dataclass
class StoredValue:
    """Rich value returned when a store uses return_type='stored'."""
    value: bytes
    metadata: Dict[str, Any]
    ttl_remaining: Optional[int] = None

    @property
    def bytes(self) -> bytes:
        return self.value

    @property
    def encoding(self) -> Optional[str]:
        return self.metadata.get("encoding")

    @property
    def content_type(self) -> Optional[str]:
        return self.metadata.get("content_type")

    @property
    def created_at(self) -> Optional[str]:
        return self.metadata.get("created_at")

    @property
    def etag(self) -> Optional[str]:
        return self.metadata.get("checksum")

    @property
    def text(self) -> str:
        encoding = self.encoding or DEFAULT_ENCODING
        return self.value.decode(encoding)


class QueryBuilder:
    """Small fluent query builder over NADB metadata."""

    def __init__(self, store: "KeyValueStore"):
        self.store = store
        self.tags: List[str] = []
        self.filters: Dict[str, Any] = {}
        self.prefix_value: Optional[str] = None
        self.limit_value: Optional[int] = None
        self.offset_value: int = 0
        self.order_field: str = "key"
        self.order_reverse: bool = False

    def tag(self, tag: str) -> "QueryBuilder":
        self.tags.append(tag)
        return self

    def where(self, field: str, value: Any) -> "QueryBuilder":
        self.filters[field] = value
        return self

    def prefix(self, prefix: str) -> "QueryBuilder":
        self.prefix_value = prefix
        return self

    def limit(self, limit: int) -> "QueryBuilder":
        self.limit_value = limit
        return self

    def offset(self, offset: int) -> "QueryBuilder":
        self.offset_value = offset
        return self

    def order_by(self, field: str, reverse: bool = False) -> "QueryBuilder":
        self.order_field = field
        self.order_reverse = reverse
        return self

    def all(self) -> List[Dict[str, Any]]:
        return self.store.query_metadata(
            tags=self.tags or None,
            prefix=self.prefix_value,
            order_by=self.order_field,
            reverse=self.order_reverse,
            limit=self.limit_value,
            offset=self.offset_value,
            **self.filters
        )

    def keys(self) -> List[str]:
        return [item["key"] for item in self.all()]


class _StoreWriter(io.BytesIO):
    """BytesIO writer that commits to a key on close."""

    def __init__(self, store: "KeyValueStore", key: str, tags: Optional[List[str]], chunk_size: Optional[int]):
        super().__init__()
        self.store = store
        self.key = key
        self.tags = tags
        self.chunk_size = chunk_size
        self._committed = False

    def close(self):
        if not self._committed:
            data = self.getvalue()
            if self.chunk_size:
                self.store.set_chunked(self.key, data, self.chunk_size, self.tags)
            else:
                self.store.set_bytes(self.key, data, self.tags)
            self._committed = True
        super().close()


class KeyValueStore:
    """A key-value store that persists data to disk with advanced features."""

    def __init__(
        self,
        data_folder_path: str = "./data",
        db: str = "default",
        buffer_size_mb: float = DEFAULT_BUFFER_SIZE_MB,
        namespace: str = DEFAULT_NAMESPACE,
        sync: Optional['KeyValueSync'] = None,
        compression_enabled: bool = True,
        storage_backend: str = "fs",
        enable_transactions: bool = True,
        enable_backup: bool = True,
        enable_indexing: bool = True,
        cache_size: int = 10000,
        storage_options: Optional[Dict[str, Any]] = None,
        allow_backend_fallback: bool = False,
        default_encoding: str = DEFAULT_ENCODING,
        return_type: ReturnType = "bytes",
        encryption_key: Optional[Union[str, bytes]] = None,
        cache_ttl_seconds: Optional[int] = None,
        max_cache_memory_bytes: Optional[int] = None,
        enable_otel: bool = False
    ) -> None:
        self._validate_identifier(db, "db", MAX_DB_LENGTH)
        self._validate_identifier(namespace, "namespace", MAX_NAMESPACE_LENGTH)
        self.data_folder_path = data_folder_path
        self.buffer_size_mb = buffer_size_mb
        self.db = db
        self.namespace = namespace
        self.default_encoding = default_encoding
        self.return_type = return_type
        self.encryption_key = encryption_key.encode(default_encoding) if isinstance(encryption_key, str) else encryption_key
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_memory_bytes = max_cache_memory_bytes
        self.enable_otel = enable_otel
        self._watchers: Dict[str, List[Callable[..., None]]] = defaultdict(list)
        self._validators: List[Callable[[str, bytes, Dict[str, Any]], None]] = []
        self._transformers: List[Callable[[str, bytes, Dict[str, Any]], Union[bytes, Tuple[bytes, Dict[str, Any]]]]] = []
        self._custom_indexes: Dict[str, Dict[Any, Set[str]]] = defaultdict(lambda: defaultdict(set))
        self._indexed_fields: Set[str] = set()
        self._otel_counters = defaultdict(int)
        self._owns_sync = sync is None
        self.buffer = {}  # In-memory buffer
        self.current_buffer_size = 0
        self.buffer_lock = threading.RLock()  # Lock for buffer operations
        self.locks = {}
        self.locks_management_lock = threading.RLock()
        
        # Initialize logging (if available)
        if LOGGING_AVAILABLE:
            self.logger = LoggingConfig.get_logger('keyvaluestore')
            self.perf_logger = LoggingConfig.get_performance_logger('storage')
        else:
            import logging
            self.logger = logging.getLogger('nadb.keyvaluestore')
            self.perf_logger = None
        
        # Initialize the storage backend
        storage_kwargs = {"base_path": data_folder_path}
        if storage_options:
            storage_kwargs.update(storage_options)
        self.storage = StorageFactory.create_storage(
            storage_backend,
            allow_backend_fallback=allow_backend_fallback,
            **storage_kwargs
        )

        # Get backend capabilities
        self.capabilities = self.storage.get_capabilities()

        # DEPRECATED: Keep for backward compatibility; internal code should use capabilities.
        self.is_redis_backend = storage_backend == "redis"

        # Determine write strategy based on capabilities
        self.use_buffering = self.capabilities.supports_buffering and \
                            self.capabilities.write_strategy != "immediate"

        # Connect to the metadata database only if backend doesn't support metadata
        if not self.capabilities.supports_metadata:
            self.metadata = KeyValueMetadata(f'{db}_meta.db', data_folder_path)
        else:
            # Backend handles metadata internally
            self.metadata = None
        
        # Setup metrics
        self.metrics = PerformanceMetrics()
        
        # Setup directory
        os.makedirs(data_folder_path, exist_ok=True)
        
        # Register with sync engine
        self.sync = sync or KeyValueSync(flush_interval_seconds=1)
        if self._owns_sync:
            self.sync.start()
        self.sync.register_store(self)
        
        # Compression
        self.compression_enabled = compression_enabled
        
        # Initialize advanced features (if available)
        if enable_transactions and TRANSACTIONS_AVAILABLE:
            self.transaction_manager = TransactionManager(self)
        else:
            self.transaction_manager = None
            if enable_transactions and not TRANSACTIONS_AVAILABLE:
                self.logger.warning("Transactions requested but not available - install advanced features")
        
        if enable_backup and BACKUP_AVAILABLE:
            self.backup_manager = BackupManager(self)
        else:
            self.backup_manager = None
            if enable_backup and not BACKUP_AVAILABLE:
                self.logger.warning("Backup requested but not available - install advanced features")

        self._reconcile_metadata()

        if enable_indexing and INDEXING_AVAILABLE:
            self.index_manager = IndexManager(self, cache_size)
            if cache_ttl_seconds is not None:
                self.index_manager.query_cache.default_ttl = cache_ttl_seconds
                self.index_manager.metadata_cache.default_ttl = cache_ttl_seconds
            if max_cache_memory_bytes is not None:
                approx_items = max(1, max_cache_memory_bytes // 512)
                self.index_manager.query_cache.max_size = min(self.index_manager.query_cache.max_size, approx_items)
                self.index_manager.metadata_cache.max_size = min(self.index_manager.metadata_cache.max_size, approx_items)
        else:
            self.index_manager = None
            if enable_indexing and not INDEXING_AVAILABLE:
                self.logger.warning("Indexing requested but not available - install advanced features")

        self.logger.info(f"KeyValueStore initialized: {db}.{namespace} on {storage_backend} backend")

    def _get_hash(self, key: str) -> str:
        """Get hash of the key for use in file naming."""
        # Use blake2b which is fast and produces shorter hash than SHA
        h = blake2b(digest_size=16)
        h.update(f"{self.db}:{self.namespace}:{key}".encode('utf-8'))
        return h.hexdigest()

    @classmethod
    def open(cls, *args, **kwargs):
        """Open a store that can be used as a context manager."""
        return cls(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    @staticmethod
    def _validate_identifier(value: str, field_name: str, max_length: int) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} must be a non-empty string")
        if len(value) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        if "\x00" in value:
            raise ValueError(f"{field_name} must not contain NUL bytes")

    def _validate_key(self, key: str) -> None:
        self._validate_identifier(key, "Key", MAX_KEY_LENGTH)

    def _validate_tags(self, tags: Optional[List[str]]) -> None:
        if tags is None:
            return
        if not isinstance(tags, list):
            raise TypeError("Tags must be a list")
        for tag in tags:
            self._validate_identifier(tag, "Tag", MAX_TAG_LENGTH)

    def _safe_key(self, key: str) -> str:
        return blake2b(key.encode("utf-8"), digest_size=8).hexdigest()

    def _normalize_value(
        self,
        value: ValueInput,
        encoding: Optional[str] = None,
        content_type: Optional[str] = None,
        value_type: Optional[str] = None
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Convert supported public values to bytes and return type metadata."""
        encoding = encoding or self.default_encoding
        if isinstance(value, str):
            data = value.encode(encoding)
            metadata = {
                "value_type": value_type or "text",
                "encoding": encoding,
                "content_type": content_type or "text/plain; charset=" + encoding,
            }
        elif isinstance(value, bytes):
            data = value
            metadata = {
                "value_type": value_type or "bytes",
                "encoding": None,
                "content_type": content_type or "application/octet-stream",
            }
        elif isinstance(value, (bytearray, memoryview)):
            data = bytes(value)
            metadata = {
                "value_type": value_type or "bytes",
                "encoding": None,
                "content_type": content_type or "application/octet-stream",
            }
        else:
            raise TypeError("Value must be str, bytes, bytearray, or memoryview")
        return data, metadata

    def _checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _validate_value_size(self, data: bytes) -> None:
        max_size = self.capabilities.max_value_size_bytes
        if max_size is not None and len(data) > max_size:
            raise ValueError(f"Value size {len(data)} exceeds backend limit of {max_size} bytes")

    def _xor_crypt(self, data: bytes) -> bytes:
        if not self.encryption_key:
            return data
        out = bytearray()
        counter = 0
        while len(out) < len(data):
            block = hashlib.sha256(self.encryption_key + counter.to_bytes(8, "big")).digest()
            out.extend(block)
            counter += 1
        return bytes(b ^ k for b, k in zip(data, out))

    def _prepare_for_storage(self, data: bytes) -> bytes:
        return self._xor_crypt(data) if self.encryption_key else data

    def _restore_from_storage(self, data: bytes, metadata: Optional[Dict[str, Any]]) -> bytes:
        if metadata and metadata.get("encrypted"):
            return self._xor_crypt(data)
        return data

    def _record_otel(self, operation: str, **attrs):
        self._otel_counters[operation] += 1
        if not self.enable_otel:
            return
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer("nadb")
            with tracer.start_as_current_span(f"nadb.{operation}") as span:
                for key, value in attrs.items():
                    span.set_attribute(key, value)
        except Exception:
            # OpenTelemetry is intentionally optional.
            return

    def _emit_event(self, event: str, key: Optional[str] = None, **payload):
        for callback in list(self._watchers.get(event, [])) + list(self._watchers.get("*", [])):
            try:
                callback(event=event, key=key, store=self, **payload)
            except Exception as exc:
                self.logger.warning(f"Watcher for {event} failed: {exc}")

    def watch(self, event: str, callback: Callable[..., None]):
        """Register a callback for set/delete/expire/restore events."""
        self._watchers[event].append(callback)
        return callback

    def unwatch(self, event: str, callback: Callable[..., None]) -> bool:
        if callback in self._watchers.get(event, []):
            self._watchers[event].remove(callback)
            return True
        return False

    def add_validator(self, validator: Callable[[str, bytes, Dict[str, Any]], None]):
        self._validators.append(validator)
        return validator

    def add_transformer(self, transformer: Callable[[str, bytes, Dict[str, Any]], Union[bytes, Tuple[bytes, Dict[str, Any]]]]):
        self._transformers.append(transformer)
        return transformer

    def _apply_hooks(self, key: str, value: bytes, metadata: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
        for transformer in self._transformers:
            result = transformer(key, value, metadata)
            if isinstance(result, tuple):
                value, extra = result
                metadata.update(extra or {})
            elif result is not None:
                value = result
        for validator in self._validators:
            validator(key, value, metadata)
        return value, metadata

    def _format_return_value(self, key: str, value: bytes, metadata: Optional[Dict[str, Any]]) -> Union[bytes, str, StoredValue]:
        if self.return_type == "bytes":
            return value
        if self.return_type == "str":
            encoding = (metadata or {}).get("encoding") or self.default_encoding
            return value.decode(encoding)
        if self.return_type == "stored":
            ttl_remaining = None
            try:
                ttl_remaining = self.ttl(key)
            except Exception:
                ttl_remaining = None
            return StoredValue(value=value, metadata=metadata or {}, ttl_remaining=ttl_remaining)
        raise ValueError("return_type must be 'bytes', 'str', or 'stored'")

    def _reconcile_metadata(self) -> None:
        """Remove metadata entries whose value is missing on startup."""
        try:
            entries = self._query_metadata({"db": self.db, "namespace": self.namespace})
            removed = 0
            for entry in entries:
                if not self.storage.file_exists(entry["path"]):
                    self._delete_metadata(entry["key"])
                    removed += 1
            if removed:
                self.logger.warning(f"Removed {removed} metadata entries with missing stored values")
        except Exception as exc:
            self.logger.warning(f"Metadata reconciliation skipped: {exc}")
        
    def _get_path(self, key: str) -> str:
        """Get the relative path for the key's storage location."""
        key_hash = self._get_hash(key)
        # Create a directory structure: /dbname/hash[0:2]/hash[2:4]/full_hash
        relative_path = os.path.join(self.db, key_hash[0:2], key_hash[2:4], key_hash)
        return relative_path
        
    def _should_flush(self) -> bool:
        """Check if the buffer should be flushed to disk."""
        # Convert MB to bytes
        max_size_bytes = self.buffer_size_mb * 1024 * 1024
        return self.current_buffer_size >= max_size_bytes
        
    def flush_if_needed(self):
        """Flush the buffer to disk if it's reached the size threshold."""
        if self._should_flush():
            self._flush_to_disk()
            
    def _should_compress(self, data: bytes) -> bool:
        """Determine if data should be compressed based on size."""
        if not self.compression_enabled:
            return False
        return len(data) > COMPRESS_MIN_SIZE
        
    def _compress_data(self, data: bytes) -> bytes:
        """Compress data using zlib."""
        return self.storage.compress_data(data, self.compression_enabled)
        
    def _decompress_data(self, data: bytes) -> bytes:
        """Decompress data if it was compressed."""
        return self.storage.decompress_data(data)
        
    def _is_compressed(self, data: bytes) -> bool:
        """Check if data has the compression header."""
        return self.storage._is_compressed(data)

    def _get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a key (unified interface).

        Returns metadata regardless of whether backend supports it or uses SQLite.
        """
        if self.capabilities.supports_metadata:
            return self.storage.get_metadata(key, self.db, self.namespace)
        else:
            return self.metadata.get_metadata(key, self.db, self.namespace)

    def _set_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Set metadata for a key (unified interface).

        Stores metadata regardless of whether backend supports it or uses SQLite.
        """
        if self.capabilities.supports_metadata:
            return self.storage.set_metadata(metadata)
        else:
            self.metadata.set_metadata(metadata)
            return True

    def _delete_metadata(self, key: str) -> bool:
        """
        Delete metadata for a key (unified interface).

        Deletes metadata regardless of whether backend supports it or uses SQLite.
        """
        if self.capabilities.supports_metadata:
            return self.storage.delete_metadata(key, self.db, self.namespace)
        else:
            self.metadata.delete_metadata(key, self.db, self.namespace)
            return True

    def _query_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Query metadata (unified interface).

        Queries metadata regardless of whether backend supports it or uses SQLite.
        """
        if self.capabilities.supports_metadata:
            return self.storage.query_metadata(query)
        else:
            return self.metadata.query_metadata(query)
        
    def _flush_to_disk(self):
        """Write buffered data to disk with atomic buffer swap to prevent race conditions."""
        # Atomic swap: acquire lock, swap buffer, release lock
        with self.buffer_lock:
            if not self.buffer:
                return

            # Atomic swap - new buffer for new writes, old buffer for flushing
            buffer_to_flush = self.buffer
            self.buffer = {}
            size_to_flush = self.current_buffer_size
            self.current_buffer_size = 0

        # Now flush the old buffer without holding the lock
        # This allows new writes to proceed concurrently
        failed_items = {}

        for key, value in buffer_to_flush.items():
            start_time = time.time()
            try:
                # Get file path
                path = self._get_path(key)

                # Get lock for this key
                with self._get_lock(key):
                    stored_value = self._prepare_for_storage(value)
                    data_to_write = self._compress_data(stored_value)

                    # Write data to file using storage backend
                    success = self.storage.write_data(path, data_to_write)

                    if success:
                        # Update metadata
                        existing_metadata = self._get_metadata(key) or {}
                        metadata = {
                            **existing_metadata,
                            "path": path,
                            "key": key,
                            "db": self.db,
                            "namespace": self.namespace,
                            "size": existing_metadata.get("logical_size", len(value)),
                            "logical_size": existing_metadata.get("logical_size", len(value)),
                            "stored_size": len(data_to_write),
                            "checksum": existing_metadata.get("checksum") or self._checksum(value),
                            "encrypted": bool(self.encryption_key) or existing_metadata.get("encrypted", False),
                            "ttl": existing_metadata.get("ttl"),
                            "expires_at": existing_metadata.get("expires_at"),
                        }
                        # Use unified metadata interface
                        self._set_metadata(metadata)
                    else:
                        # Track failed writes for re-adding
                        failed_items[key] = value

                duration_ms = (time.time() - start_time) * 1000
                self.metrics.record_operation('flush', duration_ms, len(value))

            except Exception as e:
                logging.error(f"Error flushing key hash {self._safe_key(key)} to disk: {str(e)}")
                # Track failed writes for re-adding
                failed_items[key] = value

        # Re-add failed items to buffer atomically
        if failed_items:
            with self.buffer_lock:
                for key, value in failed_items.items():
                    # Only add if not already in buffer (might have been updated)
                    if key not in self.buffer:
                        self.buffer[key] = value
                        self.current_buffer_size += len(value)
                
    def _write_key_to_disk(self, key, value, metadata_extra: Optional[Dict[str, Any]] = None):
        """Write a single key-value pair to disk.
        
        Args:
            key: The key to write
            value: The value to write
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get file path
            path = self._get_path(key)
            
            stored_value = self._prepare_for_storage(value)
            data_to_write = self._compress_data(stored_value)
            
            # Write data to file using storage backend
            success = self.storage.write_data(path, data_to_write)
            
            if success:
                # Update metadata (without TTL)
                metadata = {
                    "path": path,
                    "key": key,
                    "db": self.db,
                    "namespace": self.namespace,
                    "size": len(value),
                    "logical_size": len(value),
                    "stored_size": len(data_to_write),
                    "checksum": self._checksum(value),
                    "encrypted": bool(self.encryption_key),
                }
                if metadata_extra:
                    metadata.update(metadata_extra)
                # Use unified metadata interface
                self._set_metadata(metadata)
                
            return success
        except Exception as e:
            logging.error(f"Error writing key hash {self._safe_key(key)} to disk: {e}")
            return False

    def _immediate_set(
        self,
        key: str,
        value: bytes,
        tags: List[str] = None,
        ttl: int = None,
        value_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Immediate write strategy - write directly to storage without buffering.

        Used for backends like Redis that are fast and don't benefit from buffering.
        """
        data_len = len(value)
        self._validate_value_size(value)
        path = self._get_path(key)
        expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat() if ttl else None
        metadata = {
            "path": path,
            "key": key,
            "db": self.db,
            "namespace": self.namespace,
            "size": data_len,
            "logical_size": data_len,
            "stored_size": None,
            "checksum": self._checksum(value),
            "encrypted": bool(self.encryption_key),
            "ttl": ttl,
            "expires_at": expires_at,
        }
        if value_metadata:
            metadata.update(value_metadata)
        value, metadata = self._apply_hooks(key, value, metadata)
        stored_value = self._prepare_for_storage(value)
        data_to_write = self._compress_data(stored_value)
        metadata.update({
            "size": len(value),
            "logical_size": len(value),
            "stored_size": len(data_to_write),
            "checksum": self._checksum(value),
            "encrypted": bool(self.encryption_key),
        })
        if tags:
            metadata["tags"] = tags

        success = self.storage.write_data(path, data_to_write)
        if not success:
            self.logger.error(f"Immediate write failed for key hash {self._safe_key(key)}")
            raise IOError(f"Failed to write key {key} to storage backend")

        if not self._set_metadata(metadata):
            self.storage.delete_file(path)
            raise IOError(f"Failed to write metadata for key {key}")

        # Update indexes
        if self.index_manager:
            self.index_manager.add_key_to_indexes(key, tags or [], metadata)
        self._update_custom_indexes_for_key(key, metadata, value)
        self._emit_event("set", key, metadata=metadata)
        self._record_otel("set", db=self.db, namespace=self.namespace)

        # Remove from buffer if it exists (edge case)
        with self.buffer_lock:
            if key in self.buffer:
                self.current_buffer_size -= len(self.buffer[key])
                del self.buffer[key]

    def _buffered_set(
        self,
        key: str,
        value: bytes,
        tags: List[str] = None,
        ttl: int = None,
        value_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Buffered write strategy - write to in-memory buffer first.

        Used for backends like filesystem that benefit from batched writes.
        """
        data_len = len(value)
        self._validate_value_size(value)
        expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat() if ttl else None
        metadata = {
            "path": self._get_path(key),
            "key": key,
            "db": self.db,
            "namespace": self.namespace,
            "size": data_len,
            "logical_size": data_len,
            "stored_size": None,
            "checksum": self._checksum(value),
            "encrypted": bool(self.encryption_key),
            "ttl": ttl,
            "expires_at": expires_at,
        }
        if value_metadata:
            metadata.update(value_metadata)
        value, metadata = self._apply_hooks(key, value, metadata)
        data_len = len(value)
        metadata.update({
            "size": data_len,
            "logical_size": data_len,
            "checksum": self._checksum(value),
            "encrypted": bool(self.encryption_key),
        })

        # Use buffer_lock to prevent race conditions with flush
        with self.buffer_lock:
            # Adjust size if key already exists
            if key in self.buffer:
                self.current_buffer_size -= len(self.buffer[key])
            self.buffer[key] = value
            self.current_buffer_size += data_len
        if tags:
            metadata["tags"] = tags

        self._set_metadata(metadata)

        # Update indexes
        if self.index_manager:
            self.index_manager.add_key_to_indexes(key, tags or [], metadata)
        self._update_custom_indexes_for_key(key, metadata, value)
        self._emit_event("set", key, metadata=metadata)
        self._record_otel("set", db=self.db, namespace=self.namespace)

        # Check if we need to flush the buffer
        self.flush_if_needed()

    def set(
        self,
        key: str,
        value: ValueInput,
        tags: List[str] = None,
        encoding: Optional[str] = None,
        content_type: Optional[str] = None,
        value_type: Optional[str] = None
    ):
        """Set a key-value pair, optionally with tags.

        Args:
            key: The key for the value (non-empty string)
            value: Text or binary data to store
            tags: Optional list of tags for search/categorization

        Raises:
            TypeError: If value is not bytes or tags is not a list of strings
            ValueError: If key is empty or None
        """
        # Input validation
        self._validate_key(key)
        self._validate_tags(tags)
        value_bytes, value_metadata = self._normalize_value(value, encoding, content_type, value_type)

        safe_key = self._safe_key(key)
        op_id = f"set_{safe_key}_{int(time.time() * 1000)}"
        if self.perf_logger:
            self.perf_logger.start_operation(op_id, "set", key_hash=safe_key, data_size=len(value_bytes))

        try:
            with self._get_lock(key):
                # Use write strategy based on backend capabilities
                if self.use_buffering:
                    self._buffered_set(key, value_bytes, tags, value_metadata=value_metadata)
                else:
                    self._immediate_set(key, value_bytes, tags, value_metadata=value_metadata)

            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=True)

        except Exception as e:
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Failed to set key hash {safe_key}: {e}")
            raise
            
    def set_with_ttl(
        self,
        key: str,
        value: ValueInput,
        ttl_seconds: int,
        tags: List[str] = None,
        encoding: Optional[str] = None,
        content_type: Optional[str] = None,
        value_type: Optional[str] = None
    ):
        """Set a key-value pair with a time-to-live.

        Args:
            key: The key for the value
            value: Binary data to store
            ttl_seconds: Time to live in seconds
            tags: Optional list of tags for search/categorization

        Raises:
            TypeError: If value is not bytes
            ValueError: If TTL is not a positive integer
        """
        self._validate_key(key)
        self._validate_tags(tags)
        value_bytes, value_metadata = self._normalize_value(value, encoding, content_type, value_type)
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("TTL must be a positive integer")

        start_time = time.time()

        try:
            with self._get_lock(key):
                # TTL always uses immediate write (even on FS backend)
                # This ensures TTL tracking starts immediately
                if self.capabilities.supports_native_ttl:
                    # Backend has native TTL support (Redis)
                    self._immediate_set(key, value_bytes, tags, ttl=ttl_seconds, value_metadata=value_metadata)
                else:
                    # Backend doesn't have native TTL - use buffering but mark for TTL tracking
                    # For now, force immediate write for TTL consistency
                    self._immediate_set(key, value_bytes, tags, ttl=ttl_seconds, value_metadata=value_metadata)

            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation('set_with_ttl', duration_ms, len(value_bytes))

        except Exception as e:
            self.logger.error(f"Failed to set key hash {self._safe_key(key)} with TTL: {e}")
            raise
            
    def get(self, key: str) -> bytes:
        """Get value for a key.

        Args:
            key: The key to retrieve (non-empty string)

        Returns:
            The value as bytes

        Raises:
            KeyError: If key doesn't exist
            ValueError: If key is empty or None
        """
        # Input validation
        self._validate_key(key)

        start_time = time.time()

        try:
            # First check the in-memory buffer
            with self._get_lock(key):
                if key in self.buffer:
                    value = self.buffer[key]
                    metadata = self._get_metadata(key)
                    # Record the operation and return
                    duration_ms = (time.time() - start_time) * 1000
                    self.metrics.record_operation('get', duration_ms, len(value))
                    self._record_otel("get", db=self.db, namespace=self.namespace, cache_hit=True)
                    return self._format_return_value(key, value, metadata)
                    
                # If not in buffer, get metadata to check if it exists
                metadata = self._get_metadata(key)
                
                if not metadata:
                    raise KeyError(f"Key '{key}' not found")
                    
                # Get the path
                path = metadata["path"]
                
                # Read data using storage backend
                value = self.storage.read_data(path)
                
                if value is None:
                    # The key might have expired if using Redis TTL
                    self.metrics.record_operation('get_miss', (time.time() - start_time) * 1000)
                    raise KeyError(f"Key '{key}' not found or expired")
                    
                # Decompress if needed
                value = self._decompress_data(value)
                value = self._restore_from_storage(value, metadata)
                checksum = metadata.get("checksum") if metadata else None
                if checksum and self._checksum(value) != checksum:
                    raise ValueError(f"Checksum mismatch for key '{key}'")
                
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation('get', duration_ms, len(value))
            self._record_otel("get", db=self.db, namespace=self.namespace, cache_hit=False)
            return self._format_return_value(key, value, metadata)
            
        except KeyError:
            # Key doesn't exist, record the failed operation
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation('get_miss', duration_ms)
            raise
            
    def get_with_metadata(self, key: str) -> Dict[str, Any]:
        """Get a value with its associated metadata.

        Args:
            key: The key to retrieve

        Returns:
            Dictionary with 'value' and 'metadata' keys
        """
        value = self.get_bytes(key)  # This will raise KeyError if the key doesn't exist
        metadata = self._get_metadata(key)
        return {"value": value, "metadata": metadata}

    def get_bytes(self, key: str) -> bytes:
        """Get a value as bytes."""
        old_return_type = self.return_type
        self.return_type = "bytes"
        try:
            return self.get(key)
        finally:
            self.return_type = old_return_type

    def get_text(self, key: str, encoding: Optional[str] = None) -> str:
        """Get a value decoded as text."""
        result = self.get_with_metadata(key)
        metadata = result.get("metadata") or {}
        effective_encoding = encoding or metadata.get("encoding") or self.default_encoding
        return result["value"].decode(effective_encoding)

    def set_text(self, key: str, value: str, tags: List[str] = None, encoding: Optional[str] = None,
                 content_type: Optional[str] = None):
        """Store text data."""
        return self.set(key, value, tags=tags, encoding=encoding, content_type=content_type)

    def set_bytes(self, key: str, value: ValueInput, tags: List[str] = None,
                  content_type: Optional[str] = None):
        """Store binary data."""
        value_bytes, _ = self._normalize_value(value, content_type=content_type)
        return self.set(key, value_bytes, tags=tags, content_type=content_type)

    def set_json(self, key: str, value: Any, tags: List[str] = None, **json_kwargs):
        """Serialize and store a JSON value as UTF-8 text."""
        data = json.dumps(value, **json_kwargs)
        return self.set(key, data, tags=tags, content_type="application/json", value_type="json")

    def get_json(self, key: str) -> Any:
        """Read and deserialize a JSON value."""
        return json.loads(self.get_text(key))

    def get_or_none(self, key: str) -> Optional[bytes]:
        """Return a value or None when the key does not exist."""
        try:
            return self.get(key)
        except KeyError:
            return None

    def get_or_default(self, key: str, default: Any = None) -> Any:
        """Return a value or the supplied default when the key does not exist."""
        try:
            return self.get(key)
        except KeyError:
            return default

    def exists(self, key: str) -> bool:
        """Return True if the key exists."""
        self._validate_key(key)
        with self._get_lock(key):
            if key in self.buffer:
                return True
            metadata = self._get_metadata(key)
            return bool(metadata and self.storage.file_exists(metadata["path"]))

    def ttl(self, key: str) -> Optional[int]:
        """Return remaining TTL seconds, None for persistent keys, or raise KeyError."""
        self._validate_key(key)
        metadata = self._get_metadata(key)
        if not metadata:
            raise KeyError(f"Key '{key}' not found")
        expires_at = metadata.get("expires_at")
        if not expires_at:
            ttl_value = metadata.get("ttl")
            updated = metadata.get("last_updated")
            if ttl_value and updated:
                expires_at = (datetime.fromisoformat(updated) + timedelta(seconds=int(ttl_value))).isoformat()
            else:
                return None
        remaining = int((datetime.fromisoformat(expires_at) - datetime.now()).total_seconds())
        return max(0, remaining)

    def set_with_expires_at(self, key: str, value: ValueInput, expires_at: datetime,
                            tags: List[str] = None, **kwargs):
        ttl_seconds = int((expires_at - datetime.now()).total_seconds())
        if ttl_seconds <= 0:
            raise ValueError("expires_at must be in the future")
        return self.set_with_ttl(key, value, ttl_seconds, tags=tags, **kwargs)

    def set_with_timedelta(self, key: str, value: ValueInput, ttl: timedelta,
                           tags: List[str] = None, **kwargs):
        return self.set_with_ttl(key, value, int(ttl.total_seconds()), tags=tags, **kwargs)

    def persist_ttl(self, key: str):
        """Remove expiration from a key."""
        metadata = self._get_metadata(key)
        if not metadata:
            raise KeyError(f"Key '{key}' not found")
        metadata["ttl"] = None
        metadata["expires_at"] = None
        self._set_metadata(metadata)
        return True

    def get_stored(self, key: str) -> StoredValue:
        old_return_type = self.return_type
        self.return_type = "stored"
        try:
            return self.get(key)
        finally:
            self.return_type = old_return_type

    def set_many(self, items: Union[Dict[str, ValueInput], Iterable[Tuple[str, ValueInput]]],
                 tags: List[str] = None, atomic: bool = False) -> Dict[str, bool]:
        pairs = items.items() if isinstance(items, dict) else items
        results = {}
        if atomic:
            with self.transaction() as tx:
                for key, value in pairs:
                    tx.set(key, value, tags)
                    results[key] = True
            return results
        for key, value in pairs:
            try:
                self.set(key, value, tags=tags)
                results[key] = True
            except Exception:
                results[key] = False
        return results

    def get_many(self, keys: Iterable[str], default: Any = None) -> Dict[str, Any]:
        return {key: self.get_or_default(key, default) for key in keys}

    def delete_many(self, keys: Iterable[str], atomic: bool = False) -> Dict[str, bool]:
        results = {}
        if atomic:
            with self.transaction() as tx:
                for key in keys:
                    tx.delete(key)
                    results[key] = True
            return results
        for key in keys:
            try:
                self.delete(key)
                results[key] = True
            except Exception:
                results[key] = False
        return results

    def exists_many(self, keys: Iterable[str]) -> Dict[str, bool]:
        return {key: self.exists(key) for key in keys}

    def compare_and_set(self, key: str, expected_etag: Optional[str], value: ValueInput,
                        tags: List[str] = None, **kwargs) -> bool:
        metadata = self._get_metadata(key)
        current = metadata.get("checksum") if metadata else None
        if current != expected_etag:
            return False
        self.set(key, value, tags=tags, **kwargs)
        return True

    def set_if_version(self, key: str, expected_etag: Optional[str], value: ValueInput,
                       tags: List[str] = None, **kwargs) -> bool:
        return self.compare_and_set(key, expected_etag, value, tags, **kwargs)

    def set_if_absent(self, key: str, value: ValueInput, tags: List[str] = None, **kwargs) -> bool:
        if self.exists(key):
            return False
        self.set(key, value, tags=tags, **kwargs)
        return True

    def set_if_exists(self, key: str, value: ValueInput, tags: List[str] = None, **kwargs) -> bool:
        if not self.exists(key):
            return False
        self.set(key, value, tags=tags, **kwargs)
        return True

    def touch(self, key: str, ttl_seconds: Optional[int] = None) -> bool:
        metadata = self._get_metadata(key)
        if not metadata:
            return False
        if ttl_seconds:
            metadata["ttl"] = ttl_seconds
            metadata["expires_at"] = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        else:
            metadata["last_accessed"] = datetime.now().isoformat()
        self._set_metadata(metadata)
        return True

    def incr(self, key: str, amount: int = 1) -> int:
        try:
            raw = self.get_bytes(key)
        except KeyError:
            raw = b"0"
        current = int(raw.decode(self.default_encoding))
        new_value = current + amount
        self.set_text(key, str(new_value), content_type="text/plain")
        return new_value

    def decr(self, key: str, amount: int = 1) -> int:
        return self.incr(key, -amount)

    def delete(self, key: str) -> None:
        """Delete a key-value pair.

        Args:
            key: The key to delete (non-empty string)

        Raises:
            ValueError: If key is empty or None
        """
        # Input validation
        self._validate_key(key)

        safe_key = self._safe_key(key)
        op_id = f"delete_{safe_key}_{int(time.time() * 1000)}"
        if self.perf_logger:
            self.perf_logger.start_operation(op_id, "delete", key_hash=safe_key)
        
        try:
            with self._get_lock(key):
                # Remove from buffer if it exists
                with self.buffer_lock:
                    if key in self.buffer:
                        size = len(self.buffer[key])
                        del self.buffer[key]
                        self.current_buffer_size -= size

                # Get metadata
                metadata = self._get_metadata(key)

                if not metadata:
                    return  # Key doesn't exist, nothing to do

                # Remove from indexes
                if self.index_manager:
                    self.index_manager.remove_key_from_indexes(key)
                for field_indexes in self._custom_indexes.values():
                    for keys in field_indexes.values():
                        keys.discard(key)

                # Delete the file if it exists using storage backend
                path = metadata["path"]
                self.storage.delete_file(path)

                # Delete metadata
                self._delete_metadata(key)
                self._emit_event("delete", key, metadata=metadata)
                self._record_otel("delete", db=self.db, namespace=self.namespace)
            
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=True)
            
        except Exception as e:
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Failed to delete key hash {safe_key}: {e}")
            raise
            
    def _get_lock(self, key: str) -> threading.RLock:
        """Get a lock for the specified key with automatic cleanup of unused locks."""
        with self.locks_management_lock:
            if key not in self.locks:
                self.locks[key] = threading.RLock()

            # Periodic cleanup: remove locks that aren't currently held
            # Only cleanup every 1000 lock requests to avoid overhead
            if not hasattr(self, '_lock_request_count'):
                self._lock_request_count = 0
            self._lock_request_count += 1

            if self._lock_request_count >= 1000:
                self._lock_request_count = 0
                self._cleanup_unused_locks()

            return self.locks[key]

    def _cleanup_unused_locks(self) -> None:
        """Remove locks that are not currently held by any thread."""
        # Must be called while holding locks_management_lock
        keys_to_remove = []
        for key, lock in self.locks.items():
            # Try to acquire the lock without blocking
            # If we can acquire it, no one is using it
            if lock.acquire(blocking=False):
                lock.release()
                # Only remove if key is not in buffer (might be needed soon)
                if key not in self.buffer:
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.locks[key]

        if keys_to_remove:
            self.logger.debug(f"Cleaned up {len(keys_to_remove)} unused locks")
            
    def flush(self):
        """Flush all buffered data to disk."""
        self._flush_to_disk()
        
    def flushdb(self, confirm: bool = False, scope: str = "namespace"):
        """Clear all data for this database."""
        if confirm is not True:
            self.logger.warning("flushdb called without confirm=True; this compatibility path will require confirmation in a future release")
        if scope not in {"namespace", "db", "all"}:
            raise ValueError("scope must be 'namespace', 'db', or 'all'")
        start_time = time.time()
        
        # Clear the buffer
        with self.buffer_lock:
            self.buffer.clear()
            self.current_buffer_size = 0

        query = {}
        if scope in {"namespace", "db"}:
            query["db"] = self.db
        if scope == "namespace":
            query["namespace"] = self.namespace
        entries = self._query_metadata(query)

        for entry in entries:
            self.storage.delete_file(entry["path"])
            self._delete_metadata(entry["key"])
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('flushdb', duration_ms)
        self._emit_event("flushdb", None, scope=scope, count=len(entries))
        
    @property
    def name(self):
        """Return a unique name for this store."""
        return f"{self.db}:{self.namespace}"
        
    def query_by_tags(self, tags: list):
        """Query for keys that have all the specified tags.
        
        Args:
            tags: List of tags to query for
            
        Returns:
            List of keys with their metadata
        """
        start_time = time.time()
        
        self._validate_tags(tags)
        results = self._query_metadata({
            "db": self.db,
            "namespace": self.namespace,
            "tags": tags
        })
        
        keys_metadata = {}
        for metadata in results:
            keys_metadata[metadata["key"]] = metadata
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('query_by_tags', duration_ms)
        
        return keys_metadata
        
    def list_all_tags(self):
        """List all tags in the database."""
        entries = self._query_metadata({"db": self.db, "namespace": self.namespace})
        tag_counts = defaultdict(int)
        for entry in entries:
            for tag in entry.get("tags", []):
                tag_counts[tag] += 1
        return dict(tag_counts)

    def scan_keys(self, prefix: Optional[str] = None, page_size: int = 100) -> Iterator[List[str]]:
        """Yield pages of keys without requiring callers to load all pages at once."""
        keys = self.keys_with_prefix(prefix or "")
        for idx in range(0, len(keys), page_size):
            yield keys[idx:idx + page_size]

    def keys_with_prefix(self, prefix: str = "") -> List[str]:
        entries = self._query_metadata({"db": self.db, "namespace": self.namespace})
        return sorted(entry["key"] for entry in entries if entry["key"].startswith(prefix))

    def list_namespaces(self, prefix: Optional[str] = None) -> List[str]:
        entries = self._query_metadata({"db": self.db})
        namespaces = sorted({entry["namespace"] for entry in entries})
        if prefix:
            namespaces = [namespace for namespace in namespaces if namespace.startswith(prefix)]
        return namespaces

    def clear_namespace(self, namespace: Optional[str] = None, confirm: bool = False) -> int:
        if not confirm:
            raise ValueError("clear_namespace requires confirm=True")
        target_namespace = namespace or self.namespace
        entries = self._query_metadata({"db": self.db, "namespace": target_namespace})
        for entry in entries:
            self.storage.delete_file(entry["path"])
            if target_namespace == self.namespace:
                self._delete_metadata(entry["key"])
            elif self.capabilities.supports_metadata:
                self.storage.delete_metadata(entry["key"], self.db, target_namespace)
            else:
                self.metadata.delete_metadata(entry["key"], self.db, target_namespace)
        return len(entries)

    def query_metadata(self, tags: Optional[List[str]] = None, prefix: Optional[str] = None,
                       order_by: str = "key", reverse: bool = False,
                       limit: Optional[int] = None, offset: int = 0, **filters) -> List[Dict[str, Any]]:
        query = {"db": self.db, "namespace": self.namespace}
        if tags:
            query["tags"] = tags
        entries = self._query_metadata(query)
        if prefix:
            entries = [entry for entry in entries if entry["key"].startswith(prefix)]
        for field, value in filters.items():
            entries = [entry for entry in entries if entry.get(field) == value]
        entries.sort(key=lambda item: item.get(order_by) or "", reverse=reverse)
        if offset:
            entries = entries[offset:]
        if limit is not None:
            entries = entries[:limit]
        return entries

    def query(self) -> QueryBuilder:
        return QueryBuilder(self)

    def create_index(self, field: str):
        self._indexed_fields.add(field)
        self._rebuild_custom_index(field)

    def query_index(self, field: str, value: Any) -> List[str]:
        if field not in self._indexed_fields:
            self.create_index(field)
        return sorted(self._custom_indexes[field].get(value, set()))

    def _extract_index_value(self, field: str, metadata: Dict[str, Any], value: Optional[bytes] = None):
        if field in metadata:
            return metadata.get(field)
        if value is not None and metadata.get("content_type") == "application/json":
            try:
                document = json.loads(value.decode(metadata.get("encoding") or self.default_encoding))
                return document.get(field)
            except Exception:
                return None
        return None

    def _rebuild_custom_index(self, field: str):
        self._custom_indexes[field].clear()
        for entry in self._query_metadata({"db": self.db, "namespace": self.namespace}):
            value = None
            if field not in entry and entry.get("content_type") == "application/json":
                try:
                    value = self.get_bytes(entry["key"])
                except Exception:
                    value = None
            indexed_value = self._extract_index_value(field, entry, value)
            if indexed_value is not None:
                self._custom_indexes[field][indexed_value].add(entry["key"])

    def _update_custom_indexes_for_key(self, key: str, metadata: Dict[str, Any], value: Optional[bytes] = None):
        for field in self._indexed_fields:
            for keys in self._custom_indexes[field].values():
                keys.discard(key)
            indexed_value = self._extract_index_value(field, metadata, value)
            if indexed_value is not None:
                self._custom_indexes[field][indexed_value].add(key)
        
    def cleanup_expired(self):
        """Clean up expired entries."""
        if self.capabilities.supports_native_ttl:
            # Use Redis's native TTL handling plus custom cleanup
            expired = self.storage.cleanup_expired()
            for item in expired:
                self._emit_event("expire", item.get("key"), metadata=item)
            return expired
        else:
            # Original implementation but ensure files are deleted
            expired_items = self.metadata.cleanup_expired()
            
            # For filesystem backend, we need to make sure the files are deleted
            for item in expired_items:
                key = item["key"]
                # Remove from buffer if present
                if key in self.buffer:
                    size = len(self.buffer[key])
                    del self.buffer[key]
                    self.current_buffer_size -= size
                
                # Delete the actual file
                path = item["path"]
                self.storage.delete_file(path)
                self._emit_event("expire", key, metadata=item)
            
            return expired_items
        
    def compact_storage(self):
        """Optimize storage by removing unnecessary files and compressing data."""
        # Flush pending changes first
        self.flush()
        
        start_time = time.time()
        
        if self.capabilities.is_distributed:
            entries = self._query_metadata({"db": self.db, "namespace": self.namespace})
            stats = {
                'remote_compaction': 'No local compaction needed for this backend',
                'total_keys': len(entries),
                'total_size_bytes': sum(e.get('stored_size') or e.get('size') or 0 for e in entries),
                # For backward compatibility with tests
                'files_processed': len(entries),
                'files_compressed': 0,
                'files_missing': 0,
                'size_before_bytes': sum(e.get('stored_size') or e.get('size') or 0 for e in entries),
                'size_after_bytes': sum(e.get('stored_size') or e.get('size') or 0 for e in entries),
                'time_taken_ms': 0
            }
            return stats
        else:
            # Original implementation for non-Redis backends
            # Get all entries for this store
            entries = self.metadata.query_metadata({
                "db": self.db,
                "namespace": self.namespace
            })
            
            stats = {
                'total_entries': len(entries),
                'compressed': 0,
                'already_compressed': 0,
                'not_compressible': 0,
                'too_small': 0,
                'errors': 0,
                'bytes_before': 0,
                'bytes_after': 0,
                # For backward compatibility with tests
                'files_processed': 0,
                'files_compressed': 0,
                'files_missing': 0,
                'size_before_bytes': 0,
                'size_after_bytes': 0
            }
            
            # Process each entry
            for entry in entries:
                try:
                    path = entry["path"]
                    key = entry["key"]
                    size = entry.get("size", 0)
                    
                    # Skip small files if compression is enabled
                    if size < COMPRESS_MIN_SIZE:
                        stats['too_small'] += 1
                        continue
                        
                    # Read the data
                    data = self.storage.read_data(path)
                    if not data:
                        stats['files_missing'] += 1  # For backward compatibility
                        continue
                        
                    stats['bytes_before'] += len(data)
                    stats['size_before_bytes'] += len(data)  # For backward compatibility
                    stats['files_processed'] += 1  # For backward compatibility
                    
                    # Check if already compressed
                    if self._is_compressed(data):
                        stats['already_compressed'] += 1
                        stats['bytes_after'] += len(data)
                        stats['size_after_bytes'] += len(data)  # For backward compatibility
                        continue
                        
                    # Try to compress
                    if self._should_compress(data) and self.compression_enabled:
                        compressed_data = self._compress_data(data)
                        
                        # Check if compression was effective
                        if len(compressed_data) < len(data):
                            # Write back the compressed data
                            self.storage.write_data(path, compressed_data)
                            
                            # Update metadata
                            entry["size"] = len(compressed_data)
                            self._set_metadata(entry)
                            
                            stats['compressed'] += 1
                            stats['files_compressed'] += 1  # For backward compatibility
                            stats['bytes_after'] += len(compressed_data)
                            stats['size_after_bytes'] += len(compressed_data)  # For backward compatibility
                        else:
                            stats['not_compressible'] += 1
                            stats['bytes_after'] += len(data)
                            stats['size_after_bytes'] += len(data)  # For backward compatibility
                    else:
                        stats['not_compressible'] += 1
                        stats['bytes_after'] += len(data)
                        stats['size_after_bytes'] += len(data)  # For backward compatibility
                        
                except Exception as e:
                    logging.error(f"Error during compaction for {entry.get('key', 'unknown')}: {e}")
                    stats['errors'] += 1
            
            duration_ms = (time.time() - start_time) * 1000
            stats['duration_ms'] = duration_ms
            stats['time_taken_ms'] = duration_ms  # For backward compatibility
            self.metrics.record_operation('compact_storage', duration_ms)
            
            return stats

    def get_stats(self):
        """Get statistics about this store."""
        # Ensure we have up-to-date data
        self.flush()
        
        entries = self._query_metadata({
            "db": self.db,
            "namespace": self.namespace
        })

        total_size = sum(entry.get("stored_size") or entry.get("size") or 0 for entry in entries)

        all_tags = set()
        for entry in entries:
            tags = entry.get("tags", [])
            all_tags.update(tags)

        stats = {
            'db': self.db,
            'namespace': self.namespace,
            'count': len(entries),
            'size_bytes': total_size,
            'logical_size_bytes': sum(entry.get("logical_size") or entry.get("size") or 0 for entry in entries),
            'tag_count': len(all_tags),
            'buffer_size_bytes': self.current_buffer_size,
            'buffer_utilization_percent': 0 if self.buffer_size_mb <= 0 else (
                self.current_buffer_size / (self.buffer_size_mb * 1024 * 1024)
            ) * 100,
            'performance': self.metrics.get_metrics()
        }

        if self.index_manager:
            stats['index_stats'] = self.index_manager.get_index_stats()
            stats['cache_stats'] = self.index_manager.get_cache_stats()
            stats['query_stats'] = self.index_manager.get_query_stats()

        if self.transaction_manager:
            stats['active_transactions'] = len(self.transaction_manager.get_active_transactions())

        return stats
    
    # Transaction Methods
    def transaction(self, isolation_level: str = "READ_COMMITTED"):
        """Create a transaction context manager."""
        if not self.transaction_manager:
            raise RuntimeError("Transactions not enabled for this store")
        return self.transaction_manager.transaction(isolation_level)
    
    def begin_transaction(self, isolation_level: str = "READ_COMMITTED"):
        """Begin a new transaction."""
        if not self.transaction_manager:
            raise RuntimeError("Transactions not enabled for this store")
        return self.transaction_manager.begin_transaction(isolation_level)
    
    def commit_transaction(self, transaction):
        """Commit a transaction."""
        if not self.transaction_manager:
            raise RuntimeError("Transactions not enabled for this store")
        return self.transaction_manager.commit_transaction(transaction)
    
    def rollback_transaction(self, transaction):
        """Rollback a transaction."""
        if not self.transaction_manager:
            raise RuntimeError("Transactions not enabled for this store")
        return self.transaction_manager.rollback_transaction(transaction)
    
    # Backup Methods
    def create_backup(self, backup_id: Optional[str] = None, compression: bool = True):
        """Create a full backup."""
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.create_full_backup(backup_id, compression)
    
    def create_incremental_backup(self, parent_backup_id: str, backup_id: Optional[str] = None, compression: bool = True):
        """Create an incremental backup."""
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.create_incremental_backup(parent_backup_id, backup_id, compression)
    
    def restore_backup(self, backup_id: str, verify_integrity: bool = True, clear_existing: bool = False):
        """Restore from a backup."""
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.restore_backup(backup_id, verify_integrity, clear_existing)
    
    def list_backups(self):
        """List all available backups."""
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.list_backups()
    
    def verify_backup(self, backup_id: str):
        """Verify backup integrity."""
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.verify_backup_integrity(backup_id)
    
    # Advanced Query Methods
    def query_by_tags_advanced(self, tags: List[str], operator: str = "AND", page: int = 1, page_size: int = 100):
        """Advanced tag query with pagination."""
        if not self.index_manager:
            # Fallback to original method
            results = self.query_by_tags(tags)
            keys = list(results.keys())
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            return {
                'keys': keys[start_idx:end_idx],
                'total_count': len(keys),
                'page': page,
                'page_size': page_size,
                'has_more': end_idx < len(keys)
            }
        
        if INDEXING_AVAILABLE:
            query_op = QueryOperator.AND if operator.upper() == "AND" else QueryOperator.OR
            return self.index_manager.query_by_tags(tags, query_op, page, page_size)
        else:
            # Fallback if indexing not available
            results = self.query_by_tags(tags)
            keys = list(results.keys())
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            return {
                'keys': keys[start_idx:end_idx],
                'total_count': len(keys),
                'page': page,
                'page_size': page_size,
                'has_more': end_idx < len(keys)
            }
    
    def complex_query(self, conditions: List[Dict[str, Any]], page: int = 1, page_size: int = 100):
        """Execute complex queries with multiple conditions."""
        if not self.index_manager:
            raise RuntimeError("Advanced querying not enabled for this store")
        
        if not INDEXING_AVAILABLE:
            raise RuntimeError("Advanced indexing features not available")
        
        from index_manager import QueryCondition, QueryOperator
        
        # Convert dict conditions to QueryCondition objects
        query_conditions = []
        for cond in conditions:
            operator = QueryOperator(cond.get('operator', 'and'))
            query_conditions.append(QueryCondition(
                field=cond['field'],
                operator=operator,
                value=cond.get('value'),
                values=cond.get('values'),
                min_value=cond.get('min_value'),
                max_value=cond.get('max_value')
            ))
        
        return self.index_manager.complex_query(query_conditions, page, page_size)
    
    def optimize_indexes(self):
        """Optimize indexes based on usage patterns."""
        if self.index_manager:
            self.index_manager.optimize_indexes()
    
    def rebuild_indexes(self):
        """Rebuild all indexes from scratch."""
        if self.index_manager:
            self.index_manager.rebuild_indexes()
    
    def clear_caches(self):
        """Clear all caches."""
        if self.index_manager:
            self.index_manager.clear_caches()

    def open_reader(self, key: str) -> io.BytesIO:
        """Open a binary reader for a stored value."""
        return io.BytesIO(self.get_bytes(key))

    def open_writer(self, key: str, tags: List[str] = None, chunk_size: Optional[int] = None) -> io.BytesIO:
        """Open a binary writer that stores its contents when closed."""
        return _StoreWriter(self, key, tags, chunk_size)

    def set_chunked(self, key: str, value: ValueInput, chunk_size: int = 1024 * 1024,
                    tags: List[str] = None):
        """Store a large value as chunk records plus a manifest."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        data, value_metadata = self._normalize_value(value)
        chunk_keys = []
        for index in range(0, len(data), chunk_size):
            chunk = data[index:index + chunk_size]
            chunk_key = f"{key}.__chunk__.{index // chunk_size:08d}"
            self.set_bytes(chunk_key, chunk, tags=(tags or []) + ["nadb:chunk"])
            chunk_keys.append(chunk_key)
        manifest = {
            "chunked": True,
            "key": key,
            "chunk_size": chunk_size,
            "chunks": chunk_keys,
            "logical_size": len(data),
            "checksum": self._checksum(data),
            "value_metadata": value_metadata,
        }
        self.set_json(key, manifest, tags=(tags or []) + ["nadb:manifest"])

    def get_chunked(self, key: str) -> bytes:
        manifest = self.get_json(key)
        if not manifest.get("chunked"):
            raise ValueError(f"Key '{key}' is not a chunk manifest")
        data = b"".join(self.get_bytes(chunk_key) for chunk_key in manifest["chunks"])
        if self._checksum(data) != manifest["checksum"]:
            raise ValueError(f"Checksum mismatch for chunked key '{key}'")
        return data

    def export_backup_stream(self, output_path: str, include_data: bool = True) -> str:
        """Export a JSONL backup stream with a manifest header."""
        self.flush()
        entries = self._query_metadata({"db": self.db, "namespace": self.namespace})
        manifest = {
            "format": "nadb-jsonl",
            "version": 1,
            "db": self.db,
            "namespace": self.namespace,
            "created_at": datetime.now().isoformat(),
            "count": len(entries),
        }
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"manifest": manifest}) + "\n")
            for entry in entries:
                item = {"metadata": entry}
                if include_data:
                    item["value"] = base64.b64encode(self.get_bytes(entry["key"])).decode("ascii")
                f.write(json.dumps(item, default=str) + "\n")
        return output_path

    def import_backup_stream(self, input_path: str, clear_existing: bool = False) -> int:
        """Import a JSONL backup stream created by export_backup_stream."""
        if clear_existing:
            self.flushdb(confirm=True)
        restored = 0
        with open(input_path, "r", encoding="utf-8") as f:
            first = f.readline()
            if not first:
                return 0
            for line in f:
                item = json.loads(line)
                metadata = item.get("metadata", {})
                if "value" not in item:
                    continue
                value = base64.b64decode(item["value"])
                self.set(metadata["key"], value, tags=metadata.get("tags"))
                restored += 1
                self._emit_event("restore", metadata["key"], metadata=metadata)
        return restored

    def export_backup_tar(self, output_path: str) -> str:
        """Export a tar archive containing a JSONL backup stream."""
        jsonl_path = output_path + ".jsonl"
        self.export_backup_stream(jsonl_path)
        with tarfile.open(output_path, "w") as tar:
            tar.add(jsonl_path, arcname="backup.jsonl")
        try:
            os.remove(jsonl_path)
        except OSError:
            pass
        return output_path

    def prune_backups(self, keep_last: int = 10, keep_days: int = 30) -> int:
        if not self.backup_manager:
            raise RuntimeError("Backup not enabled for this store")
        return self.backup_manager.cleanup_old_backups(keep_days=keep_days, keep_count=keep_last)

    def get_otel_metrics(self) -> Dict[str, int]:
        """Return lightweight operation counters used with optional OpenTelemetry."""
        return dict(self._otel_counters)
    
    def get_all_keys(self) -> List[str]:
        """Get all keys from the store (for backup purposes)."""
        try:
            results = self._query_metadata({
                'db': self.db,
                'namespace': self.namespace
            })
            return [r['key'] for r in results]
        except Exception as e:
            self.logger.error(f"Failed to get all keys: {e}")
            return []

    def close(self):
        """Close the store and all resources."""
        if self._owns_sync and self.sync:
            self.sync.sync_exit()
        self.flush()
        
        # Close database connections
        if self.metadata:
            self.metadata.close_connections()
        
        # Close storage connections
        if hasattr(self.storage, 'close_connections'):
            self.storage.close_connections()
        
        # Clean up managers
        if self.transaction_manager:
            self.transaction_manager.cleanup_stale_transactions(0)  # Clean all
        
        self.logger.info(f"KeyValueStore {self.db}.{self.namespace} closed")


def open_store(*args, **kwargs) -> KeyValueStore:
    """Convenience factory for opening a NADB store."""
    return KeyValueStore.open(*args, **kwargs)


if __name__ == '__main__':
    # Usage example
    import tempfile
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as data_dir:
        # Create the sync manager
        sync_manager = KeyValueSync(flush_interval_seconds=5)
        sync_manager.start()
        
        try:
            # Create a key-value store with compression enabled
            kv_store = KeyValueStore(
                data_folder_path=data_dir,
                db="testdb",
                buffer_size_mb=1,
                namespace="default",
                sync=sync_manager,
                compression_enabled=True,
                enable_transactions=False,  # Disable advanced features for basic example
                enable_backup=False,
                enable_indexing=False
            )
            
            print("Testing basic key-value operations...")
            
            # Store text data with tags
            text_data = "Hello, world!".encode('utf-8')
            kv_store.set("text_key", text_data, tags=["text", "greeting"])
            
            # Store binary data (e.g., image)
            print("Creating sample binary data...")
            binary_data = bytes([0x89, 0x50, 0x4E, 0x47] + [i % 256 for i in range(100)])
            kv_store.set("binary_key", binary_data, tags=["binary", "image"])
            
            # Store larger data to demonstrate compression
            print("Creating larger data to demonstrate compression...")
            large_data = b"x" * 10000  # 10KB of data
            kv_store.set("large_key", large_data, tags=["large"])
            
            # Store data with TTL
            print("Setting data with TTL...")
            ttl_data = "This will expire".encode('utf-8')
            kv_store.set_with_ttl("ttl_key", ttl_data, ttl_seconds=300, tags=["temporary"])
            
            # Retrieve data
            print("Retrieved text data:", kv_store.get("text_key").decode('utf-8'))
            binary_result = kv_store.get("binary_key")
            print(f"Retrieved binary data of length {len(binary_result)} bytes")
            
            # Query by tags
            print("\nQuerying by tags:")
            text_keys = kv_store.query_by_tags(["text"])
            print("Keys with 'text' tag:", text_keys)
            
            binary_keys = kv_store.query_by_tags(["binary"])
            print("Keys with 'binary' tag:", binary_keys)
            
            # Get with metadata
            print("\nRetrieving with metadata:")
            _, metadata = kv_store.get_with_metadata("text_key")
            print(f"Metadata for text_key: {metadata}")
            
            # List all tags
            print("\nAll tags in store:", kv_store.list_all_tags())
            
            # Force a flush to demonstrate persistence
            print("\nFlushing to disk...")
            kv_store.flush()
            
            # Run compaction
            print("\nRunning storage compaction...")
            compaction_results = kv_store.compact_storage()
            print(f"Compaction results: {compaction_results}")
            
            # Get performance statistics
            print("\nPerformance statistics:")
            stats = kv_store.get_stats()
            print(f"Total items: {stats['count']}")
            print(f"Buffer utilization: {stats['buffer_utilization_percent']:.2f}%")
            print(f"Operations: {stats['performance']['operations']}")
            
            # Check sync status
            print("\nSync status:", sync_manager.status())
            
        finally:
            # Cleanup
            print("\nCleaning up...")
            sync_manager.sync_exit()
            print("Done")
