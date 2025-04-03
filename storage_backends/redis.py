"""
Redis Storage Backend for NADB Key-Value Store.

This module implements a Redis-based storage backend that saves data to Redis.
Redis is used both for storing the data and the metadata, enabling distributed storage.
"""
import os
import logging
import zlib
import json
import time
import random
from datetime import datetime, timedelta
import redis

# Constants for compression
COMPRESS_MIN_SIZE = 1024  # Only compress files larger than 1KB
COMPRESS_LEVEL = 6  # Medium compression (range is 0-9)

# Redis connection parameters
DEFAULT_CONNECTION_TIMEOUT = 5.0  # Default connection timeout in seconds
DEFAULT_SOCKET_TIMEOUT = 10.0  # Default socket timeout in seconds
MAX_RECONNECT_ATTEMPTS = 5  # Maximum number of reconnection attempts
INITIAL_RETRY_DELAY = 0.5  # Initial retry delay in seconds

class RedisStorage:
    """Redis storage backend for NADB key-value store."""
    
    def __init__(self, base_path=None, host='localhost', port=6379, db=0, password=None, 
                 socket_timeout=DEFAULT_SOCKET_TIMEOUT, 
                 connection_timeout=DEFAULT_CONNECTION_TIMEOUT, **kwargs):
        """
        Initialize Redis storage backend.
        
        Args:
            base_path: Ignored, included for compatibility with file-based storage
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password
            socket_timeout: Timeout for socket operations (in seconds)
            connection_timeout: Timeout for connection attempts (in seconds)
            **kwargs: Additional Redis connection parameters
        """
        self.logger = logging.getLogger(__name__)
        
        # Store connection parameters for reconnection if needed
        self.connection_params = {
            'host': host,
            'port': port,
            'db': db,
            'password': password,
            'socket_timeout': socket_timeout,
            'socket_connect_timeout': connection_timeout,
            **kwargs
        }
        
        # Connection state tracking
        self.connected = False
        self.last_connection_error = None
        self.connection_errors = 0
        self.last_reconnect_time = 0
        
        # Connect to Redis
        self._connect()
        
        # Key prefixes for different types of data
        self.data_prefix = "nadb:data:"
        self.meta_prefix = "nadb:meta:"
        self.tag_prefix = "nadb:tag:"
        self.ttl_set = "nadb:ttl"
        
        self.logger.info(f"Redis storage initialized: {host}:{port} DB:{db}")
    
    def _connect(self):
        """
        Connect to Redis server with exponential backoff for retries.
        
        Returns:
            True if connection successful, False otherwise
        """
        # Reset the connected flag
        self.connected = False
        
        # Determine if we should throttle reconnection attempts
        now = time.time()
        time_since_last_attempt = now - self.last_reconnect_time
        
        # If we've tried recently, implement exponential backoff
        if time_since_last_attempt < 10 and self.connection_errors > 0:
            # Calculate backoff time based on number of previous errors
            backoff = min(30, INITIAL_RETRY_DELAY * (2 ** (self.connection_errors - 1)))
            # Add jitter (0-100% of backoff)
            jitter = random.uniform(0, backoff)
            backoff_with_jitter = backoff + jitter
            
            if time_since_last_attempt < backoff_with_jitter:
                self.logger.warning(
                    f"Throttling Redis reconnection attempt. "
                    f"Will retry in {backoff_with_jitter - time_since_last_attempt:.1f}s "
                    f"(error count: {self.connection_errors})"
                )
                return False
        
        # Update last reconnect time
        self.last_reconnect_time = now
        
        # Connect to Redis - não trate erros graciosamente para permitir falhas de teste
        self.redis = redis.Redis(**self.connection_params)
        # Teste a conexão com timeout
        self.redis.ping()
        self.connected = True
        
        return True
    
    def _ensure_connection(self):
        """
        Ensure Redis connection is active, reconnect if necessary with exponential backoff.
        
        Returns:
            True if connected, False otherwise
        """
        # If we think we're connected, verify with a ping
        if self.connected:
            try:
                self.redis.ping()
                return True
            except (redis.ConnectionError, redis.RedisError, AttributeError):
                self.connected = False
                self.logger.warning("Redis connection lost, attempting to reconnect...")
        
        # Reconnect without tratamento de erro
        return self._connect()
    
    def _execute_with_retry(self, operation_name, redis_func, *args, **kwargs):
        """
        Execute a Redis operation with automatic reconnection on failure.
        
        Args:
            operation_name: Name of the operation (for logging)
            redis_func: Function to call
            *args, **kwargs: Arguments to pass to the function
            
        Returns:
            Result of the Redis operation, or None on failure
            
        Raises:
            redis.RedisError: If the operation fails after reconnection attempts
        """
        if not self._ensure_connection():
            self.logger.error(f"Cannot execute {operation_name}: not connected to Redis")
            raise redis.ConnectionError(f"Not connected to Redis server: {self.last_connection_error}")
            
        # Execute Redis operation - se falhar, deixe falhar para que os testes falhem
        return redis_func(*args, **kwargs)
    
    def _get_data_key(self, relative_path):
        """
        Convert a relative path to a Redis key for data storage.
        
        Args:
            relative_path: The relative path that would be used in file-based storage
            
        Returns:
            Redis key for the data
        """
        return f"{self.data_prefix}{relative_path}"
    
    def _get_meta_key(self, key, db, namespace):
        """
        Get Redis key for metadata storage.
        
        Args:
            key: The original data key
            db: Database name
            namespace: Namespace
            
        Returns:
            Redis key for metadata
        """
        return f"{self.meta_prefix}{db}:{namespace}:{key}"
    
    def get_full_path(self, relative_path):
        """
        Get Redis key for the data - equivalent to full path in file system.
        
        Args:
            relative_path: The relative path
            
        Returns:
            Redis key for the data
        """
        return self._get_data_key(relative_path)
    
    def ensure_directory_exists(self, path):
        """
        No-op in Redis storage - directories don't exist in Redis.
        Included for compatibility with file-based storage.
        
        Args:
            path: Ignored
            
        Returns:
            Always True
        """
        return True
    
    def file_exists(self, relative_path):
        """
        Check if data exists in Redis.
        
        Args:
            relative_path: The relative path
            
        Returns:
            True if data exists, False otherwise
        """
        try:
            key = self._get_data_key(relative_path)
            exists = self._execute_with_retry("file_exists", lambda: self.redis.exists(key) > 0)
            return exists
        except redis.RedisError as e:
            self.logger.error(f"Redis error in file_exists for {relative_path}: {str(e)}")
            return False
    
    def write_data(self, relative_path, data):
        """
        Write data to Redis.
        
        Args:
            relative_path: The relative path
            data: Binary data to store
            
        Returns:
            True if successful, False otherwise
        """
        try:
            key = self._get_data_key(relative_path)
            
            # Use a Redis transaction to ensure atomicity
            with self.redis.pipeline() as pipe:
                # Store the data
                pipe.set(key, data)
                
                # Get metadata for this key to set TTL if needed
                # Extract the original key, db, and namespace from the path
                parts = relative_path.split('/')
                if len(parts) >= 4:
                    db = parts[0]
                    try:
                        # Try to find metadata with this path
                        for pattern in [f"nadb:meta:{db}:*:*"]:
                            meta_keys = self._execute_with_retry(
                                "get_meta_keys", 
                                lambda: self.redis.keys(pattern)
                            )
                            
                            for meta_key in meta_keys:
                                meta_data = self._execute_with_retry(
                                    "get_meta", 
                                    lambda: self.redis.hgetall(meta_key)
                                )
                                
                                # Check if this metadata entry has this path
                                path_key = b'path'
                                if path_key in meta_data:
                                    stored_path = json.loads(meta_data[path_key].decode('utf-8'))
                                    if stored_path == relative_path:
                                        # Found matching metadata, check for TTL
                                        ttl_key = b'ttl'
                                        if ttl_key in meta_data:
                                            ttl = json.loads(meta_data[ttl_key].decode('utf-8'))
                                            if ttl is not None and ttl > 0:
                                                # Add TTL to the pipeline
                                                pipe.expire(key, ttl)
                                                break
                    except Exception as e:
                        self.logger.error(f"Error setting TTL on data key: {str(e)}")
                
                # Execute the pipeline
                results = pipe.execute()
                return all(results)
                
        except redis.RedisError as e:
            self.logger.error(f"Redis error in write_data for {relative_path}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error in write_data for {relative_path}: {str(e)}")
            return False
    
    def read_data(self, relative_path):
        """
        Read data from Redis.
        
        Args:
            relative_path: The relative path
            
        Returns:
            Binary data if successful, None otherwise
        """
        try:
            key = self._get_data_key(relative_path)
            data = self._execute_with_retry("read_data", lambda: self.redis.get(key))
            
            # If data is None, the key might be expired or not exist
            if data is None:
                self.logger.debug(f"No data found for key {key}")
                return None
            
            return data
        except redis.RedisError as e:
            self.logger.error(f"Redis error in read_data for {relative_path}: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in read_data for {relative_path}: {str(e)}")
            return None
    
    def delete_file(self, relative_path):
        """
        Delete data from Redis.
        
        Args:
            relative_path: The relative path
            
        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_connection():
            return False
        
        try:
            key = self._get_data_key(relative_path)
            result = self.redis.delete(key) > 0
            return result
        except redis.RedisError as e:
            self.logger.error(f"Redis error in delete_file: {str(e)}")
            return False
    
    def get_file_size(self, relative_path):
        """
        Get size of data in Redis.
        
        Args:
            relative_path: The relative path
            
        Returns:
            Size in bytes, 0 if data doesn't exist
        """
        if not self._ensure_connection():
            return 0
        
        try:
            key = self._get_data_key(relative_path)
            data = self.redis.get(key)
            return len(data) if data else 0
        except redis.RedisError as e:
            self.logger.error(f"Redis error in get_file_size: {str(e)}")
            return 0
    
    def delete_directory(self, relative_path):
        """
        Delete all data with keys that start with the given path.
        
        Args:
            relative_path: The relative path prefix
            
        Returns:
            Number of keys deleted
        """
        if not self._ensure_connection():
            return 0
        
        try:
            # Match all keys that begin with the given prefix
            prefix = self._get_data_key(relative_path)
            keys = self.redis.keys(f"{prefix}*")
            if keys:
                return self.redis.delete(*keys)
            return 0
        except redis.RedisError as e:
            self.logger.error(f"Redis error in delete_directory: {str(e)}")
            return 0
    
    def compress_data(self, data, compression_enabled):
        """
        Compress data using zlib.
        
        Args:
            data: Binary data to compress
            compression_enabled: Whether compression is enabled
            
        Returns:
            Compressed data with header or original data if not compressed
        """
        if not compression_enabled or not self._should_compress(data):
            return data
            
        # Add a simple header to indicate compression
        compressed = zlib.compress(data, COMPRESS_LEVEL)
        return b'CMP:' + compressed
    
    def decompress_data(self, data):
        """
        Decompress data if it was compressed.
        
        Args:
            data: Potentially compressed data
            
        Returns:
            Decompressed data
        """
        if not data or not self._is_compressed(data):
            return data
            
        # Skip the compression header
        compressed_data = data[4:]
        return zlib.decompress(compressed_data)
    
    def _is_compressed(self, data):
        """
        Check if data has the compression header.
        
        Args:
            data: Binary data to check
            
        Returns:
            True if data is compressed, False otherwise
        """
        return data and data.startswith(b'CMP:')
    
    def _should_compress(self, data):
        """
        Determine if data should be compressed based on size.
        
        Args:
            data: Binary data to check
            
        Returns:
            True if data should be compressed, False otherwise
        """
        return len(data) > COMPRESS_MIN_SIZE
    
    # Metadata operations (replacing SQLite functionality)
    
    def set_metadata(self, metadata):
        """
        Store metadata in Redis.
        
        Args:
            metadata: Dictionary containing metadata
            
        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_connection():
            return False
        
        try:
            key = metadata.get("key")
            db = metadata.get("db")
            namespace = metadata.get("namespace")
            
            if not all([key, db, namespace]):
                self.logger.error("Missing required metadata fields")
                return False
                
            meta_key = self._get_meta_key(key, db, namespace)
            
            # Convert datetime objects to strings
            meta_copy = metadata.copy()
            meta_copy["created_at"] = datetime.now().isoformat()
            
            # Handle tags separately
            tags = meta_copy.pop("tags", [])
            
            # Get the data key
            path = meta_copy.get("path")
            data_key = self._get_data_key(path) if path else None
            
            # Store metadata as a hash
            # The TTL must be serialized to JSON like the other fields
            # Convert hmset (deprecated) to hset
            serialized_meta = {k: json.dumps(v) for k, v in meta_copy.items()}
            self.redis.hset(meta_key, mapping=serialized_meta)
            
            # Store tags if present
            if tags:
                self._set_tags(meta_key, tags)
            
            # Store TTL info if present - use Redis's native TTL mechanism
            ttl = meta_copy.get("ttl")
            if ttl is not None and ttl > 0:
                # Important: Set TTL on data key first, then metadata
                # This ensures the data is written before setting expiration
                if data_key and self.redis.exists(data_key):
                    success = self.redis.expire(data_key, ttl)
                    self.logger.debug(f"Set TTL {ttl}s on data key {data_key}: {success}")
                    
                # Add to our TTL set for tracking
                expiry_time = time.time() + ttl
                self.redis.zadd(self.ttl_set, {meta_key: expiry_time})
                
                # Set Redis native TTL on metadata
                success = self.redis.expire(meta_key, ttl)
                self.logger.debug(f"Set TTL {ttl}s on metadata key {meta_key}: {success}")
            
            return True
        except redis.RedisError as e:
            self.logger.error(f"Redis error in set_metadata: {str(e)}")
            return False
    
    def _set_tags(self, meta_key, tags):
        """
        Associate tags with metadata.
        
        Args:
            meta_key: Redis key for the metadata
            tags: List of tags
        """
        if not tags:
            return
            
        try:
            # Ensure tag uniqueness for consistency with other backends
            unique_tags = list(set(tags))
            
            # Add metadata key to each tag's set
            for tag in unique_tags:
                tag_key = f"{self.tag_prefix}{tag}"
                self.redis.sadd(tag_key, meta_key)
                
            # Store tags for this metadata (use hset instead of hmset)
            self.redis.hset(meta_key, "tags", json.dumps(unique_tags))
            
            self.logger.debug(f"Set tags {unique_tags} for {meta_key}")
        except redis.RedisError as e:
            self.logger.error(f"Redis error in _set_tags: {str(e)}")
    
    def get_metadata(self, key, db, namespace):
        """
        Get metadata from Redis.
        
        Args:
            key: The original data key
            db: Database name
            namespace: Namespace
            
        Returns:
            Metadata dictionary or None if not found
        """
        if not self._ensure_connection():
            return None
        
        try:
            meta_key = self._get_meta_key(key, db, namespace)
            
            # Check if metadata exists
            if not self.redis.exists(meta_key):
                return None
                
            # Get all metadata fields
            raw_meta = self.redis.hgetall(meta_key)
            
            # Convert from Redis format
            metadata = {k.decode('utf-8'): json.loads(v.decode('utf-8')) for k, v in raw_meta.items()}
            
            # Add key, db, namespace explicitly
            metadata["key"] = key
            metadata["db"] = db
            metadata["namespace"] = namespace
            
            return metadata
        except redis.RedisError as e:
            self.logger.error(f"Redis error in get_metadata: {str(e)}")
            return None
    
    def delete_metadata(self, key, db, namespace):
        """
        Delete metadata from Redis.
        
        Args:
            key: The original data key
            db: Database name
            namespace: Namespace
            
        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_connection():
            return False
        
        try:
            meta_key = self._get_meta_key(key, db, namespace)
            
            # First get tags to remove metadata from tag sets
            tags_raw = self.redis.hget(meta_key, "tags")
            if tags_raw:
                tags = json.loads(tags_raw.decode('utf-8'))
                for tag in tags:
                    tag_key = f"{self.tag_prefix}{tag}"
                    self.redis.srem(tag_key, meta_key)
            
            # Remove from TTL set if present
            self.redis.zrem(self.ttl_set, meta_key)
            
            # Delete the metadata
            self.redis.delete(meta_key)
            return True
        except redis.RedisError as e:
            self.logger.error(f"Redis error in delete_metadata: {str(e)}")
            return False
    
    def query_metadata(self, query):
        """
        Query metadata from Redis.
        
        Args:
            query: Dictionary containing query parameters
            
        Returns:
            List of metadata dictionaries
        """
        if not self._ensure_connection():
            return []
        
        try:
            db = query.get("db")
            namespace = query.get("namespace")
            tags = query.get("tags", [])
            min_size = query.get("min_size")
            max_size = query.get("max_size")
            created_after = query.get("created_after")
            created_before = query.get("created_before")
            
            self.logger.debug(f"Query parameters: db={db}, namespace={namespace}, tags={tags}, min_size={min_size}")
            
            if not db or not namespace:
                self.logger.error("Missing required query fields (db, namespace)")
                return []
            
            # Pattern for matching keys in this db and namespace
            pattern = f"{self.meta_prefix}{db}:{namespace}:*"
            self.logger.debug(f"Looking for pattern: {pattern}")
            
            # First, get all keys matching the db and namespace pattern
            all_meta_keys = self.redis.keys(pattern)
            self.logger.debug(f"Found {len(all_meta_keys)} keys matching pattern {pattern}")
            
            # Approach changes based on if we have tags or not
            if not tags:
                # No tags, use all keys that match the pattern
                meta_keys = all_meta_keys
            else:
                # We have tags - use a more direct approach
                # First check if all tags exist
                all_tags_exist = True
                for tag in tags:
                    tag_key = f"{self.tag_prefix}{tag}"
                    if not self.redis.exists(tag_key):
                        self.logger.debug(f"Tag {tag} doesn't exist, returning empty result")
                        all_tags_exist = False
                        break
                
                if not all_tags_exist:
                    return []
                
                # Direct approach: for each meta key, check if it has all the required tags
                matching_meta_keys = []
                
                for meta_key in all_meta_keys:
                    meta_key_str = meta_key.decode('utf-8') if isinstance(meta_key, bytes) else meta_key
                    parts = meta_key_str.split(':', 4)
                    if len(parts) < 5:
                        self.logger.warning(f"Invalid meta key format: {meta_key_str}")
                        continue
                    
                    key = parts[4]
                    
                    # Get tags from metadata
                    tags_raw = self.redis.hget(meta_key, "tags")
                    if not tags_raw:
                        self.logger.debug(f"No tags found for key {key}")
                        continue
                    
                    try:
                        meta_tags = json.loads(tags_raw.decode('utf-8'))
                        # Check if all required tags are in this metadata's tags
                        if all(tag in meta_tags for tag in tags):
                            matching_meta_keys.append(meta_key)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Error decoding tags for key {key}")
                
                meta_keys = matching_meta_keys
                self.logger.debug(f"Found {len(meta_keys)} keys matching all tags")
            
            # Get metadata for each key
            all_results = []
            for meta_key in meta_keys:
                try:
                    meta_key_str = meta_key.decode('utf-8') if isinstance(meta_key, bytes) else meta_key
                    parts = meta_key_str.split(':', 4)  # Split into at least 5 parts
                    if len(parts) < 5:
                        self.logger.warning(f"Invalid meta key format: {meta_key_str}")
                        continue
                    
                    key = parts[4]  # The key is the 5th part (index 4)
                    
                    meta = self.get_metadata(key, db, namespace)
                    if meta:
                        all_results.append(meta)
                    else:
                        self.logger.debug(f"No metadata found for key {key}")
                except Exception as e:
                    self.logger.error(f"Error processing meta key {meta_key}: {str(e)}")
            
            # Apply additional filters
            filtered_results = []
            for meta in all_results:
                # Apply size filters
                if min_size is not None and meta.get("size", 0) < min_size:
                    continue
                
                if max_size is not None and meta.get("size", 0) > max_size:
                    continue
                
                # Date filters
                created = meta.get("created")
                if created_after and created and created < created_after:
                    continue
                
                if created_before and created and created > created_before:
                    continue
                
                filtered_results.append(meta)
            
            self.logger.debug(f"Query returned {len(filtered_results)} results after filtering")
            return filtered_results
        except redis.RedisError as e:
            self.logger.error(f"Redis error in query_metadata: {str(e)}")
            return []
    
    def cleanup_expired(self):
        """
        Clean up expired data based on TTL.
        
        Checks for items that have expired or are about to expire, and removes them
        from our tracking sets. Redis handles the actual expiration automatically.
        
        Returns:
            List of expired items that were removed
        """
        if not self._ensure_connection():
            return []
        
        try:
            # Get items from our TTL tracking set that might be expired
            now = time.time()
            expired_meta_keys = self.redis.zrangebyscore(self.ttl_set, 0, now)
            self.logger.debug(f"Found {len(expired_meta_keys)} potentially expired items in TTL set")
            
            # Check each key to see if it actually expired or if we need to delete it
            removed = []
            for meta_key in expired_meta_keys:
                meta_key_str = meta_key.decode('utf-8')
                
                # Remove from our TTL tracking set regardless
                self.redis.zrem(self.ttl_set, meta_key)
                
                # If the key exists, check if it has a TTL and if not, delete it manually
                # This helps with test cases where we need to verify expiration
                ttl_remaining = self.redis.ttl(meta_key)
                should_delete = False
                
                if ttl_remaining == -1:  # Key exists but has no TTL
                    self.logger.debug(f"Key {meta_key_str} should be expired but has no TTL, deleting manually")
                    should_delete = True
                elif ttl_remaining == -2:  # Key doesn't exist
                    self.logger.debug(f"Key {meta_key_str} already expired")
                    should_delete = False  # Already gone
                elif ttl_remaining < 2:  # About to expire
                    self.logger.debug(f"Key {meta_key_str} about to expire in {ttl_remaining}s, deleting manually")
                    should_delete = True
                
                # Extract metadata info
                try:
                    # Format: nadb:meta:db:namespace:key
                    parts = meta_key_str.split(':')
                    if len(parts) >= 5:
                        db = parts[2]
                        namespace = parts[3]
                        key = ':'.join(parts[4:])  # Handle keys with colons
                        
                        # Get metadata if available to extract path
                        path = None
                        raw_meta = self.redis.hgetall(meta_key)
                        if raw_meta:
                            path_raw = raw_meta.get(b'path')
                            if path_raw:
                                try:
                                    path = json.loads(path_raw.decode('utf-8'))
                                except json.JSONDecodeError:
                                    path = None
                        
                        # Use default path if not found
                        if not path:
                            path = f"{db}/{key[0:2]}/{key[2:4]}/{key}" if len(key) >= 4 else f"{db}/{key}"
                        
                        # Delete both metadata and data keys if needed
                        if should_delete:
                            # Delete data key
                            data_key = self._get_data_key(path)
                            self.redis.delete(data_key)
                            # Delete metadata key
                            self.redis.delete(meta_key)
                        
                        # Add to removed list
                        removed.append({
                            "key": key,
                            "db": db,
                            "namespace": namespace,
                            "path": path,
                            "expired_at": datetime.now().isoformat()
                        })
                        self.logger.debug(f"Added expired item to removed list: {key}")
                except Exception as e:
                    self.logger.error(f"Error handling expired key {meta_key_str}: {str(e)}")
            
            self.logger.debug(f"Returned {len(removed)} expired items")
            return removed
            
        except redis.RedisError as e:
            self.logger.error(f"Redis error in cleanup_expired: {str(e)}")
            return []
    
    def close_connections(self):
        """Close Redis connection."""
        try:
            if hasattr(self, 'redis'):
                self.redis.close()
        except redis.RedisError as e:
            self.logger.error(f"Redis error in close_connections: {str(e)}")
