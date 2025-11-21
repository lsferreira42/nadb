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
from hashlib import blake2b
from collections import defaultdict
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Any, Optional, Tuple, Union, Set

from storage_backends import StorageFactory

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
                ttl INTEGER DEFAULT NULL,
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
                                ttl = ?
                            WHERE path = ? AND key = ? AND db = ? AND namespace = ?'''
                    now = datetime.now().isoformat()
                    params = (
                        now,
                        now,
                        metadata.get("size"),
                        metadata.get("ttl"),
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
                                ttl
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'''
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
                        metadata.get("ttl")
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
                m.size, m.ttl, GROUP_CONCAT(t.tag_name) as tags
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
            tags = row[10].split(',') if row[10] else []
            
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
                "ttl": row[9],
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
                m.size, m.ttl, GROUP_CONCAT(t.tag_name) as tags
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
                    tags = row[10].split(',') if row[10] else []
                    
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
                        "ttl": row[9],
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
            WHERE ttl IS NOT NULL 
              AND last_updated IS NOT NULL
              AND datetime(last_updated, '+' || ttl || ' seconds') < ?
        """
        
        try:
            db_conn = self._get_db_connection()
            expired_items = []
            
            with self.connection_lock:
                cursor = db_conn.execute(sql, (now,))
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


class KeyValueStore:
    """A key-value store that persists data to disk with advanced features."""

    def __init__(
        self,
        data_folder_path: str,
        db: str,
        buffer_size_mb: float,
        namespace: str,
        sync: 'KeyValueSync',
        compression_enabled: bool = True,
        storage_backend: str = "fs",
        enable_transactions: bool = True,
        enable_backup: bool = True,
        enable_indexing: bool = True,
        cache_size: int = 10000
    ) -> None:
        self.data_folder_path = data_folder_path
        self.buffer_size_mb = buffer_size_mb
        self.db = db
        self.namespace = namespace
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
        self.storage = StorageFactory.create_storage(storage_backend, base_path=data_folder_path)
        
        # Check if we're using Redis backend
        self.is_redis_backend = storage_backend == "redis"
        
        # Connect to the metadata database only if not using Redis
        # For Redis, we'll use the storage's set_metadata method
        if not self.is_redis_backend:
            self.metadata = KeyValueMetadata(f'{db}_meta.db', data_folder_path)
        else:
            # For Redis, we'll use the storage's metadata methods
            self.metadata = None
        
        # Setup metrics
        self.metrics = PerformanceMetrics()
        
        # Setup directory
        os.makedirs(data_folder_path, exist_ok=True)
        
        # Register with sync engine
        self.sync = sync
        sync.register_store(self)
        
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
        
        if enable_indexing and INDEXING_AVAILABLE:
            self.index_manager = IndexManager(self, cache_size)
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
        return data and data.startswith(b'CMP:')
        
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
                    # Compress data if needed
                    data_to_write = self._compress_data(value)

                    # Write data to file using storage backend
                    success = self.storage.write_data(path, data_to_write)

                    if success:
                        # Update metadata
                        metadata = {
                            "path": path,
                            "key": key,
                            "db": self.db,
                            "namespace": self.namespace,
                            "size": len(data_to_write),
                            "ttl": None  # Default no TTL
                        }

                        if self.is_redis_backend:
                            # Use Redis's metadata methods
                            self.storage.set_metadata(metadata)
                        else:
                            # Use SQLite metadata
                            self.metadata.set_metadata(metadata)
                    else:
                        # Track failed writes for re-adding
                        failed_items[key] = value

                duration_ms = (time.time() - start_time) * 1000
                self.metrics.record_operation('flush', duration_ms, len(value))

            except Exception as e:
                logging.error(f"Error flushing key {key} to disk: {str(e)}")
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
                
    def _write_key_to_disk(self, key, value):
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
            
            # Compress data if needed
            data_to_write = self._compress_data(value)
            
            # Write data to file using storage backend
            success = self.storage.write_data(path, data_to_write)
            
            if success:
                # Update metadata (without TTL)
                metadata = {
                    "path": path,
                    "key": key,
                    "db": self.db,
                    "namespace": self.namespace,
                    "size": len(data_to_write),
                }
                
                if self.is_redis_backend:
                    # Use Redis's metadata methods
                    self.storage.set_metadata(metadata)
                else:
                    # Use SQLite metadata
                    self.metadata.set_metadata(metadata)
                
            return success
        except Exception as e:
            logging.error(f"Error writing key {key} to disk: {e}")
            return False

    def set(self, key: str, value: bytes, tags: List[str] = None):
        """Set a key-value pair, optionally with tags.

        Args:
            key: The key for the value (non-empty string)
            value: Binary data to store
            tags: Optional list of tags for search/categorization

        Raises:
            TypeError: If value is not bytes or tags is not a list of strings
            ValueError: If key is empty or None
        """
        # Input validation
        if not key or not isinstance(key, str):
            raise ValueError("Key must be a non-empty string")
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")
        if tags is not None:
            if not isinstance(tags, list):
                raise TypeError("Tags must be a list")
            if not all(isinstance(t, str) for t in tags):
                raise TypeError("All tags must be strings")
        
        op_id = f"set_{key}_{int(time.time() * 1000)}"
        if self.perf_logger:
            self.perf_logger.start_operation(op_id, "set", key=key, data_size=len(value))
        
        try:
            data_len = len(value)
            
            with self._get_lock(key):
                if self.is_redis_backend:
                    path = self._get_path(key)
                    data_to_write = self._compress_data(value)
                    success = self.storage.write_data(path, data_to_write)
                    if success:
                        metadata = {
                            "path": path,
                            "key": key,
                            "db": self.db,
                            "namespace": self.namespace,
                            "size": data_len,  # Use original size for metadata
                            "ttl": None
                        }
                        if tags:
                            metadata["tags"] = tags
                        self.storage.set_metadata(metadata)
                        
                        # Update indexes
                        if self.index_manager:
                            self.index_manager.add_key_to_indexes(key, tags or [], metadata)
                        
                        # Remove from buffer if it exists
                        if key in self.buffer:
                             self.current_buffer_size -= len(self.buffer[key])
                             del self.buffer[key]
                    else:
                        self.logger.error(f"Immediate Redis write failed for key {key}")
                        raise IOError(f"Failed to write key {key} to Redis backend")
                else:
                    # Original behavior for non-Redis backends (buffering)
                    # Use buffer_lock to prevent race conditions with flush
                    with self.buffer_lock:
                        # Adjust size if key already exists
                        if key in self.buffer:
                            self.current_buffer_size -= len(self.buffer[key])
                        self.buffer[key] = value
                        self.current_buffer_size += data_len

                    # Update metadata (SQLite)
                    metadata = {
                        "path": self._get_path(key),
                        "key": key,
                        "db": self.db,
                        "namespace": self.namespace,
                        "size": data_len,
                        "ttl": None
                    }
                    if tags:
                        metadata["tags"] = tags
                    self.metadata.set_metadata(metadata)

                    # Update indexes
                    if self.index_manager:
                        self.index_manager.add_key_to_indexes(key, tags or [], metadata)

                    # Check if we need to flush the buffer for non-Redis
                    self.flush_if_needed()
            
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=True)
            
        except Exception as e:
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Failed to set key {key}: {e}")
            raise
            
    def set_with_ttl(self, key: str, value: bytes, ttl_seconds: int, tags: list = None):
        """Set a key-value pair with a time-to-live.
        
        Args:
            key: The key for the value
            value: Binary data to store
            ttl_seconds: Time to live in seconds
            tags: Optional list of tags for search/categorization
        """
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")
            
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("TTL must be a positive integer")
            
        start_time = time.time()
        
        with self._get_lock(key):
            self.buffer[key] = value
            self.current_buffer_size += len(value)
            
            # Update metadata with TTL
            metadata = {
                "path": self._get_path(key),
                "key": key,
                "db": self.db,
                "namespace": self.namespace,
                "size": len(value),
                "ttl": ttl_seconds
            }
            
            if tags:
                metadata["tags"] = tags
            
            if self.is_redis_backend:
                # For Redis backend, TTL requires setting the expiration on the actual key
                # So we do need to write the data immediately in this case
                path = self._get_path(key)
                # Compress data if needed
                data_to_write = self._compress_data(value)
                # Write to storage directly
                success = self.storage.write_data(path, data_to_write)
                if success:
                    # Use Redis's metadata methods (will set TTL on both data and metadata)
                    self.storage.set_metadata(metadata)
                    # Remove from buffer since it's already written
                    del self.buffer[key]
                    self.current_buffer_size -= len(value)
            else:
                # Use SQLite metadata for other backends
                self.metadata.set_metadata(metadata)
                # Check if we need to flush
                self.flush_if_needed()
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('set_with_ttl', duration_ms, len(value))
            
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
        if not key or not isinstance(key, str):
            raise ValueError("Key must be a non-empty string")

        start_time = time.time()

        try:
            # First check the in-memory buffer
            with self._get_lock(key):
                if key in self.buffer:
                    value = self.buffer[key]
                    # Record the operation and return
                    duration_ms = (time.time() - start_time) * 1000
                    self.metrics.record_operation('get', duration_ms, len(value))
                    return value
                    
                # If not in buffer, get metadata to check if it exists
                if self.is_redis_backend:
                    metadata = self.storage.get_metadata(key, self.db, self.namespace)
                else:
                    metadata = self.metadata.get_metadata(key, self.db, self.namespace)
                
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
                
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_operation('get', duration_ms, len(value))
            return value
            
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
        value = self.get(key)  # This will raise KeyError if the key doesn't exist
        if self.is_redis_backend:
            metadata = self.storage.get_metadata(key, self.db, self.namespace)
        else:
            metadata = self.metadata.get_metadata(key, self.db, self.namespace)
        return {"value": value, "metadata": metadata}

    def delete(self, key: str) -> None:
        """Delete a key-value pair.

        Args:
            key: The key to delete (non-empty string)

        Raises:
            ValueError: If key is empty or None
        """
        # Input validation
        if not key or not isinstance(key, str):
            raise ValueError("Key must be a non-empty string")

        op_id = f"delete_{key}_{int(time.time() * 1000)}"
        if self.perf_logger:
            self.perf_logger.start_operation(op_id, "delete", key=key)
        
        try:
            with self._get_lock(key):
                # Remove from buffer if it exists
                if key in self.buffer:
                    size = len(self.buffer[key])
                    del self.buffer[key]
                    self.current_buffer_size -= size
                    
                # Get metadata
                if self.is_redis_backend:
                    metadata = self.storage.get_metadata(key, self.db, self.namespace)
                else:
                    metadata = self.metadata.get_metadata(key, self.db, self.namespace)
                    
                if not metadata:
                    return  # Key doesn't exist, nothing to do
                    
                # Remove from indexes
                if self.index_manager:
                    self.index_manager.remove_key_from_indexes(key)
                    
                # Delete the file if it exists using storage backend
                path = metadata["path"]
                self.storage.delete_file(path)
                    
                # Delete metadata
                if self.is_redis_backend:
                    self.storage.delete_metadata(key, self.db, self.namespace)
                else:
                    self.metadata.delete_metadata(key, self.db, self.namespace)
            
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=True)
            
        except Exception as e:
            if self.perf_logger:
                self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Failed to delete key {key}: {e}")
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
        
    def flushdb(self):
        """Clear all data for this database."""
        start_time = time.time()
        
        # Clear the buffer
        self.buffer.clear()
        self.current_buffer_size = 0
        
        if self.is_redis_backend:
            # Redis backend has a different way to query and clean up
            pattern = f"{self.storage.data_prefix}{self.db}/*"
            meta_pattern = f"{self.storage.meta_prefix}{self.db}:{self.namespace}:*"
            
            # Delete all data keys
            data_keys = self.storage.redis.keys(pattern)
            if data_keys:
                self.storage.redis.delete(*data_keys)
                
            # Delete all metadata keys
            meta_keys = self.storage.redis.keys(meta_pattern)
            if meta_keys:
                self.storage.redis.delete(*meta_keys)
                
            # Also clean up tag references (more complex since they're shared)
            tag_prefix = self.storage.tag_prefix
            tag_keys = self.storage.redis.keys(f"{tag_prefix}*")
            
            # For each tag, remove references to this db:namespace
            for tag_key in tag_keys:
                # Find metadata keys for this db:namespace in tag set
                members = self.storage.redis.smembers(tag_key)
                for m in members:
                    if m.decode('utf-8').startswith(f"{self.storage.meta_prefix}{self.db}:{self.namespace}:"):
                        # Remove from tag set
                        self.storage.redis.srem(tag_key, m)
        else:
            # Query for all entries in this db+namespace
            entries = self.metadata.query_metadata({
                "db": self.db,
                "namespace": self.namespace
            })
            
            # Delete all files
            for entry in entries:
                path = entry["path"]
                self.storage.delete_file(path)
                    
            # Delete all metadata
            for entry in entries:
                self.metadata.delete_metadata(entry["key"], self.db, self.namespace)
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('flushdb', duration_ms)
        
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
        
        if self.is_redis_backend:
            query = {
                "db": self.db,
                "namespace": self.namespace,
                "tags": tags
            }
            results = self.storage.query_metadata(query)
        else:
            results = self.metadata.query_metadata({
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
        # Implement based on backend type
        if self.is_redis_backend:
            # Use Redis tags listing
            tag_prefix = f"{self.storage.tag_prefix}"
            pattern = f"{tag_prefix}*"
            
            # Get all keys matching the tag pattern
            tag_keys = self.storage.redis.keys(pattern)
            
            # Count items for each tag
            tag_counts = {}
            for tag_key in tag_keys:
                # Extract tag name from key
                tag_name = tag_key.decode('utf-8').replace(tag_prefix, "")
                # Count members in the set
                count = self.storage.redis.scard(tag_key)
                tag_counts[tag_name] = count
                
            return tag_counts
        else:
            # Use SQLite implementation
            return self.metadata.query_tags(self.db, self.namespace)
        
    def cleanup_expired(self):
        """Clean up expired entries."""
        if self.is_redis_backend:
            # Use Redis's native TTL handling plus custom cleanup
            expired = self.storage.cleanup_expired()
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
            
            return expired_items
        
    def compact_storage(self):
        """Optimize storage by removing unnecessary files and compressing data."""
        # Flush pending changes first
        self.flush()
        
        start_time = time.time()
        
        if self.is_redis_backend:
            # For Redis backend, implement a simplified version that just reports status
            # since Redis handles storage efficiency internally
            stats = {
                'redis_compaction': 'No compaction needed for Redis backend',
                'total_keys': 0,
                'total_size_bytes': 0,
                # For backward compatibility with tests
                'files_processed': 0,
                'files_compressed': 0,
                'files_missing': 0,
                'size_before_bytes': 0,
                'size_after_bytes': 0,
                'time_taken_ms': 0
            }
            
            # Count keys and size for statistics
            pattern = f"{self.storage.data_prefix}{self.db}/*"
            meta_pattern = f"{self.storage.meta_prefix}{self.db}:{self.namespace}:*"
            
            # Get counts
            data_keys = self.storage.redis.keys(pattern)
            meta_keys = self.storage.redis.keys(meta_pattern)
            
            stats['total_keys'] = len(data_keys)
            stats['files_processed'] = len(data_keys)  # For backward compatibility
            
            # Calculate total size if desired (optional and potentially expensive)
            total_size = 0
            for key in data_keys[:100]:  # Limit to first 100 to avoid too much overhead
                try:
                    size = len(self.storage.redis.get(key) or b'')
                    total_size += size
                except:
                    pass
                    
            stats['total_size_bytes'] = total_size
            stats['size_before_bytes'] = total_size  # For backward compatibility
            stats['size_after_bytes'] = total_size   # For backward compatibility
            stats['size_estimation'] = 'Partial (first 100 keys)' if len(data_keys) > 100 else 'Complete'
            
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
                            if not self.is_redis_backend:
                                self.metadata.set_metadata(entry)
                            
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
        
        if self.is_redis_backend:
            # For Redis backend, implement a custom stats collection
            stats = {
                'db': self.db,
                'namespace': self.namespace,
                'count': 0,
                'size_bytes': 0,
                'tag_count': 0,
                'performance': self.metrics.get_metrics()
            }
            
            # Get data key pattern for this db
            data_pattern = f"{self.storage.data_prefix}{self.db}/*"
            meta_pattern = f"{self.storage.meta_prefix}{self.db}:{self.namespace}:*"
            
            # Count data keys
            data_keys = self.storage.redis.keys(data_pattern)
            meta_keys = self.storage.redis.keys(meta_pattern)
            
            stats['count'] = len(meta_keys)
            
            # Count unique tags
            tag_prefix = f"{self.storage.tag_prefix}"
            tag_keys = self.storage.redis.keys(f"{tag_prefix}*")
            stats['tag_count'] = len(tag_keys)
            
            # Calculate total size (optional, could be expensive)
            total_size = 0
            sample_size = min(100, len(data_keys))  # Limit to 100 keys to avoid overhead
            
            if sample_size > 0:
                sample_keys = data_keys[:sample_size]
                for key in sample_keys:
                    try:
                        size = len(self.storage.redis.get(key) or b'')
                        total_size += size
                    except:
                        pass
                
                # Extrapolate total size if we sampled
                if sample_size < len(data_keys):
                    stats['size_bytes'] = int(total_size * (len(data_keys) / sample_size))
                    stats['size_note'] = f"Estimated from sample of {sample_size}/{len(data_keys)} keys"
                else:
                    stats['size_bytes'] = total_size
                    stats['size_note'] = "Actual size"
            
            return stats
        else:
            # Original implementation for non-Redis backends
            # Query all entries
            entries = self.metadata.query_metadata({
                "db": self.db,
                "namespace": self.namespace
            })
            
            # Calculate statistics
            total_size = sum(entry.get("size", 0) for entry in entries)
            
            # Get unique tags
            all_tags = set()
            for entry in entries:
                tags = entry.get("tags", [])
                all_tags.update(tags)
                
            stats = {
                'db': self.db,
                'namespace': self.namespace,
                'count': len(entries),
                'size_bytes': total_size,
                'tag_count': len(all_tags),
                'performance': self.metrics.get_metrics()
            }
            
            # Add advanced feature stats
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
    
    def get_all_keys(self) -> List[str]:
        """Get all keys from the store (for backup purposes)."""
        try:
            if self.is_redis_backend:
                results = self.storage.query_metadata({
                    'db': self.db,
                    'namespace': self.namespace
                })
            else:
                results = self.metadata.query_metadata({
                    'db': self.db,
                    'namespace': self.namespace
                })
            return [r['key'] for r in results]
        except Exception as e:
            self.logger.error(f"Failed to get all keys: {e}")
            return []

    def close(self):
        """Close the store and all resources."""
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
