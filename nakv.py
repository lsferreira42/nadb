""" Simple key-value store with disk persistence and buffer management."""
import os
import json
import sqlite3
import threading
import time
import zlib
import io
import statistics
from hashlib import blake2b
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from storage_backends import StorageFactory

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

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
                    params = (
                        datetime.now(),
                        datetime.now(),
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
                    params = (
                        metadata.get("path"),
                        metadata.get("key"),
                        metadata.get("db"),
                        metadata.get("namespace"),
                        datetime.now(),
                        datetime.now(),
                        datetime.now(),
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
                    (datetime.now(), row[0])
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
            conditions.append("m.key LIKE ?")
            params.append(f"%{query['key']}%")
            
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
        now = datetime.now()
        
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
    """A key-value store that persists data to disk"""
    def __init__(self, data_folder_path: str, db: str, buffer_size_mb: float,
                 namespace: str, sync: KeyValueSync, compression_enabled: bool = True, 
                 storage_backend: str = "fs"):
        self.data_folder_path = data_folder_path
        self.buffer_size_mb = buffer_size_mb
        self.db = db
        self.namespace = namespace
        self.buffer = {}  # In-memory buffer
        self.current_buffer_size = 0
        self.locks = {}
        self.locks_management_lock = threading.RLock()
        
        # Initialize the storage backend
        self.storage = StorageFactory.create_storage(storage_backend, base_path=data_folder_path)
        
        # Connect to the metadata database
        self.metadata = KeyValueMetadata(f'{db}_meta.db', data_folder_path)
        
        # Setup metrics
        self.metrics = PerformanceMetrics()
        
        # Setup directory
        os.makedirs(data_folder_path, exist_ok=True)
        
        # Register with sync engine
        self.sync = sync
        sync.register_store(self)
        
        # Compression
        self.compression_enabled = compression_enabled

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
        """Write buffered data to disk."""
        if not self.buffer:
            return
            
        # Create a copy to allow new writes during flush
        buffer_copy = dict(self.buffer)
        self.buffer.clear()
        self.current_buffer_size = 0
        
        for key, value in buffer_copy.items():
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
                        self.metadata.set_metadata({
                            "path": path,
                            "key": key,
                            "db": self.db,
                            "namespace": self.namespace,
                            "size": len(data_to_write),
                            "ttl": None  # Default no TTL
                        })
                    else:
                        # Add it back to buffer if write failed
                        self.buffer[key] = value
                        self.current_buffer_size += len(value)
                    
                duration_ms = (time.time() - start_time) * 1000
                self.metrics.record_operation('flush', duration_ms, len(value))
                    
            except Exception as e:
                logging.error(f"Error flushing key {key} to disk: {str(e)}")
                # Add it back to buffer
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
                self.metadata.set_metadata({
                    "path": path,
                    "key": key,
                    "db": self.db,
                    "namespace": self.namespace,
                    "size": len(data_to_write),
                })
                
            return success
        except Exception as e:
            logging.error(f"Error writing key {key} to disk: {e}")
            return False

    def set(self, key: str, value: bytes, tags: list = None):
        """Set a key-value pair, optionally with tags.
        
        Args:
            key: The key for the value
            value: Binary data to store
            tags: Optional list of tags for search/categorization
        """
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")
            
        start_time = time.time()
        
        with self._get_lock(key):
            self.buffer[key] = value
            self.current_buffer_size += len(value)
            
            # Update metadata with tags
            metadata = {
                "path": self._get_path(key),
                "key": key,
                "db": self.db,
                "namespace": self.namespace,
                "size": len(value),
                "ttl": None
            }
            
            if tags:
                metadata["tags"] = tags
                
            self.metadata.set_metadata(metadata)
            
            # Check if we need to flush
            self.flush_if_needed()
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('set', duration_ms, len(value))
            
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
        
        # For the Redis backend, write data first before setting TTL
        is_redis = hasattr(self.storage, 'redis')
        
        with self._get_lock(key):
            self.buffer[key] = value
            self.current_buffer_size += len(value)
            
            # For Redis backend, we need to flush the data first
            # so the key exists before we try to set TTL on it
            if is_redis:
                path = self._get_path(key)
                # Write to storage directly
                self._write_key_to_disk(key, value)
                # Clear from buffer - we already wrote it
                del self.buffer[key]
                self.current_buffer_size -= len(value)
            
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
                
            self.metadata.set_metadata(metadata)
            
            # For non-Redis backends, use normal flush logic
            if not is_redis:
                # Check if we need to flush
                self.flush_if_needed()
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('set_with_ttl', duration_ms, len(value))
            
    def get(self, key: str):
        """Get value for a key.
        
        Args:
            key: The key to retrieve
            
        Returns:
            The value as bytes
            
        Raises:
            KeyError: If key doesn't exist
        """
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
            
    def get_with_metadata(self, key: str):
        """Get a value with its associated metadata."""
        value = self.get(key)  # This will raise KeyError if the key doesn't exist
        metadata = self.metadata.get_metadata(key, self.db, self.namespace)
        return {"value": value, "metadata": metadata}
        
    def delete(self, key: str):
        """Delete a key-value pair.
        
        Args:
            key: The key to delete
            
        Raises:
            KeyError: If key doesn't exist
        """
        start_time = time.time()
        
        with self._get_lock(key):
            # Remove from buffer if it exists
            if key in self.buffer:
                size = len(self.buffer[key])
                del self.buffer[key]
                self.current_buffer_size -= size
                
            # Get metadata
            metadata = self.metadata.get_metadata(key, self.db, self.namespace)
            if not metadata:
                return  # Key doesn't exist, nothing to do
                
            # Delete the file if it exists using storage backend
            path = metadata["path"]
            self.storage.delete_file(path)
                
            # Delete metadata
            self.metadata.delete_metadata(key, self.db, self.namespace)
            
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('delete', duration_ms)
            
    def _get_lock(self, key: str):
        """Get a lock for the specified key."""
        with self.locks_management_lock:
            if key not in self.locks:
                self.locks[key] = threading.RLock()
            return self.locks[key]
            
    def flush(self):
        """Flush all buffered data to disk."""
        self._flush_to_disk()
        
    def flushdb(self):
        """Clear all data for this database."""
        start_time = time.time()
        
        # Clear the buffer
        self.buffer.clear()
        self.current_buffer_size = 0
        
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
        """List all tags used in this database and namespace.
        
        Returns:
            Dictionary with tag counts
        """
        start_time = time.time()
        
        # Query all entries with their tags
        entries = self.metadata.query_metadata({
            "db": self.db,
            "namespace": self.namespace
        })
        
        # Count tag occurrences
        tag_counts = defaultdict(int)
        for entry in entries:
            for tag in entry.get("tags", []):
                tag_counts[tag] += 1
                
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('list_all_tags', duration_ms)
        
        return dict(tag_counts)
        
    def cleanup_expired(self):
        """Remove entries that have expired based on TTL.
        
        Returns:
            List of expired items that were removed
        """
        start_time = time.time()
        
        # Get expired entries from metadata storage backend
        expired_items = list(self.metadata.cleanup_expired())
        
        # Detect the backend type to adjust cleanup behavior
        is_redis = hasattr(self.storage, 'redis')
        
        if is_redis:
            # For Redis backend, check if the storage has a cleanup method
            if hasattr(self.storage, 'cleanup_expired'):
                # Get additional expired items from the Redis backend
                redis_expired = self.storage.cleanup_expired()
                if redis_expired:
                    expired_items.extend(redis_expired)
        else:
            # For other backends, delete corresponding files manually
            for item in expired_items:
                path = item["path"]
                self.storage.delete_file(path)
        
        # Remove expired items from buffer regardless of backend
        for item in expired_items:
            key = item["key"]
            if key in self.buffer:
                with self._get_lock(key):
                    if key in self.buffer:  # Check again inside the lock
                        size = len(self.buffer[key])
                        del self.buffer[key]
                        self.current_buffer_size -= size
                        
        duration_ms = (time.time() - start_time) * 1000
        self.metrics.record_operation('cleanup_expired', duration_ms)
        
        return expired_items
        
    def compact_storage(self):
        """Optimize storage by removing unnecessary files and compressing data."""
        # Flush pending changes first
        self.flush()
        
        start_time = time.time()
        
        # Get all entries for this store
        entries = self.metadata.query_metadata({
            "db": self.db,
            "namespace": self.namespace
        })
        
        total_size_before = 0
        total_size_after = 0
        files_processed = 0
        files_compressed = 0
        files_missing = 0
        
        for entry in entries:
            path = entry["path"]
            
            try:
                # Check if file exists
                if not self.storage.file_exists(path):
                    files_missing += 1
                    continue
                    
                # Process each file
                with self._get_lock(entry["key"]):
                    # Skip if the key is in buffer (will be written later)
                    if entry["key"] in self.buffer:
                        continue
                        
                    # Read the file
                    data = self.storage.read_data(path)
                    if data is None:
                        files_missing += 1
                        continue
                        
                    size_before = len(data)
                    total_size_before += size_before
                    
                    # Skip already compressed files
                    if self._is_compressed(data):
                        data_uncompressed = self._decompress_data(data)
                        
                        # Only compress if it's worth it
                        if not self._should_compress(data_uncompressed):
                            continue
                    else:
                        data_uncompressed = data
                        
                    # Compress the data
                    data_compressed = self._compress_data(data_uncompressed)
                    
                    # Only write if compression is beneficial
                    if len(data_compressed) < size_before:
                        # Write compressed data back
                        if self.storage.write_data(path, data_compressed):
                            # Update metadata
                            self.metadata.set_metadata({
                                "path": path,
                                "key": entry["key"],
                                "db": self.db,
                                "namespace": self.namespace,
                                "size": len(data_compressed),
                                "ttl": entry.get("ttl")
                            })
                            
                            files_compressed += 1
                        
                    total_size_after += len(data_compressed)
                    files_processed += 1
                    
            except Exception as e:
                logging.error(f"Error compacting file {path}: {str(e)}")
                
        duration_ms = (time.time() - start_time) * 1000
        
        # Record metrics
        self.metrics.record_operation('compact_storage', duration_ms)
        
        # Return statistics
        return {
            "files_processed": files_processed,
            "files_compressed": files_compressed,
            "files_missing": files_missing,
            "size_before_bytes": total_size_before,
            "size_after_bytes": total_size_after,
            "time_taken_ms": duration_ms
        }
        
    def get_stats(self):
        """Get statistics about this store."""
        # Ensure we have up-to-date data
        self.flush()
        
        # Query all entries
        entries = self.metadata.query_metadata({
            "db": self.db,
            "namespace": self.namespace
        })
        
        # Calculate statistics
        count = len(entries)
        total_size = sum(entry.get("size", 0) for entry in entries)
        avg_size = total_size / count if count > 0 else 0
        
        # Get age statistics
        now = datetime.now()
        ages = []
        
        for entry in entries:
            created_at = entry.get("created_at")
            if created_at:
                try:
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    age_seconds = (now - created_at).total_seconds()
                    ages.append(age_seconds)
                except (ValueError, TypeError):
                    pass
                    
        avg_age_seconds = statistics.mean(ages) if ages else 0
        
        # Get tag statistics
        tag_stats = self.list_all_tags()
        unique_tags = len(tag_stats)
        most_common_tags = sorted(tag_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Get buffer statistics
        buffer_items = len(self.buffer)
        buffer_size = self.current_buffer_size
        
        # Get performance metrics
        perf_metrics = self.metrics.get_metrics()
        
        return {
            "count": count,
            "total_size_bytes": total_size,
            "avg_size_bytes": avg_size,
            "avg_age_seconds": avg_age_seconds,
            "unique_tags": unique_tags,
            "most_common_tags": most_common_tags,
            "buffer_items": buffer_items,
            "buffer_size_bytes": buffer_size,
            "performance": perf_metrics
        }

    def close(self):
        """Close the store and all resources."""
        self.flush()
        # Close all database connections
        self.metadata.close_connections()


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
                compression_enabled=True
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
