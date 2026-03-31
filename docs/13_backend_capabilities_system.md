# Chapter 13: Backend Capabilities System (v2.2.0)

In earlier chapters, you learned about NADB's key features: storing data with [Tags](02_tags_.md), automatic expiration with [TTL](03_ttl__time_to_live__.md), and performance optimizations like [Data Buffering & Flushing](06_data_buffering___flushing_.md). You've also seen how NADB can use different storage mechanisms - either the filesystem (`FileSystemStorage`) or a Redis server (`RedisStorage`).

But here's an interesting question: How does the [KeyValueStore](01_keyvaluestore_.md) know *how* to work with different backends? Should it buffer data before writing? Can the backend handle TTL natively? Does it manage metadata internally or need SQLite?

Previously (before v2.2.0), this was handled with conditional checks scattered throughout the code (like `if self.is_redis_backend:`). This worked but made the code harder to maintain and extend. What if you wanted to add a PostgreSQL backend? You'd need to add more conditionals everywhere!

**NADB v2.2.0** introduces the **Backend Capabilities System** - a powerful, clean architecture where backends *describe themselves*, and `KeyValueStore` *automatically adapts* based on those descriptions.

## The Problem: Backend-Specific Code

Imagine you're building a universal remote control. If you hard-coded buttons for every possible device ("if TV, do this; if stereo, do that"), adding support for a new device would require modifying the remote's internal logic. Messy!

Similarly, NADB previously had code like:

```python
# OLD approach (before v2.2.0)
if self.is_redis_backend:
    # Redis writes immediately
    self.storage.write_data(...)
    self.storage.set_metadata(...)
else:
    # Filesystem uses buffering
    self.buffer[key] = value
    self.metadata.set_metadata(...) # External SQLite
```

This works for two backends but becomes unmanageable with more backends.

## The Solution: Self-Describing Backends

The new approach uses the **Capabilities Pattern**: each storage backend declares what it can do via a `BackendCapabilities` object. The `KeyValueStore` then reads these capabilities and adapts its behavior automatically.

Think of it like a universal remote that asks each device: "What buttons do you support?" instead of guessing.

## How It Works

### 1. Backends Declare Capabilities

Every storage backend implements a `get_capabilities()` method that returns a `BackendCapabilities` dataclass describing its features:

```python
from storage_backends.base import BackendCapabilities

class FileSystemStorage(StorageBackend):
    """Local filesystem storage."""

    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=True,      # Benefits from in-memory buffering
            supports_native_ttl=False,     # No native expiration mechanism
            supports_transactions=False,   # No ACID transactions
            supports_metadata=False,       # Uses external SQLite for metadata
            supports_atomic_writes=True,   # File system rename is atomic
            write_strategy="buffered",     # Prefer batched writes
            is_distributed=False,          # Local storage only
            is_persistent=True,            # Data survives restarts
            supports_compression=True,     # Benefits from compression
            supports_native_queries=False, # No query engine
            max_value_size_bytes=None      # No hard limit
        )
```

Meanwhile, `RedisStorage` declares different capabilities:

```python
class RedisStorage(StorageBackend):
    """Redis networked storage."""

    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=False,      # Redis is fast, no buffering needed
            supports_native_ttl=True,      # Has EXPIRE command
            supports_transactions=True,    # Has MULTI/EXEC commands
            supports_metadata=True,        # Stores metadata in Redis hashes
            supports_atomic_writes=True,   # Redis operations are atomic
            write_strategy="immediate",    # Write directly
            is_distributed=True,           # Networked storage
            is_persistent=True,            # Can persist (RDB/AOF)
            supports_compression=True,     # Can compress before storing
            supports_native_queries=False, # Limited (SCAN-based)
            max_value_size_bytes=512*1024*1024  # 512MB Redis limit
        )
```

### 2. KeyValueStore Adapts Automatically

When you create a `KeyValueStore`, it queries the backend's capabilities and configures itself accordingly:

```python
from nadb import KeyValueStore, KeyValueSync

kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

# Create store with filesystem backend
fs_store = KeyValueStore(
    data_folder_path="./fs_data",
    db="my_db",
    namespace="default",
    buffer_size_mb=1,
    sync=kv_sync,
    storage_backend="fs"  # <-- Filesystem backend
)

# Behind the scenes:
# 1. storage = FileSystemStorage(...)
# 2. capabilities = storage.get_capabilities()
# 3. use_buffering = capabilities.supports_buffering  # True!
# 4. metadata = KeyValueMetadata(...)  # SQLite (backend doesn't support metadata)

# Now create with Redis backend
redis_store = KeyValueStore(
    data_folder_path="./redis_data",
    db="my_db",
    namespace="default",
    buffer_size_mb=1,  # Ignored for Redis (doesn't buffer)
    sync=kv_sync,
    storage_backend="redis"  # <-- Redis backend
)

# Behind the scenes:
# 1. storage = RedisStorage(...)
# 2. capabilities = storage.get_capabilities()
# 3. use_buffering = False  # capabilities.supports_buffering is False
# 4. metadata = None  # Backend handles metadata (supports_metadata=True)
```

## Key Capabilities Explained

Let's break down the important capability flags:

### `supports_buffering` (bool)
- **True**: Backend benefits from in-memory buffering before writes (filesystem)
- **False**: Backend is fast enough to write directly (Redis, databases)
- **Impact**: KeyValueStore creates a memory buffer only if True

### `supports_native_ttl` (bool)
- **True**: Backend has built-in expiration (Redis EXPIRE, database triggers)
- **False**: NADB tracks TTL in metadata and uses KeyValueSync for cleanup
- **Impact**: How `set_with_ttl()` works internally

### `supports_metadata` (bool)
- **True**: Backend stores metadata alongside data (Redis hashes)
- **False**: NADB uses external SQLite database for metadata
- **Impact**: Whether `KeyValueMetadata` is created

### `write_strategy` (str)
- **"buffered"**: Prefer in-memory buffering (filesystem)
- **"immediate"**: Write directly to storage (Redis)
- **"auto"**: Let KeyValueStore decide
- **Impact**: Determines `self.use_buffering` flag

### `is_distributed` (bool)
- **True**: Backend is networked/distributed (Redis, databases)
- **False**: Backend is local (filesystem)
- **Impact**: Performance expectations, error handling

### `supports_transactions` (bool)
- **True**: Backend has native ACID transactions
- **False**: NADB implements transactions via snapshots
- **Impact**: Future optimization opportunity

## Benefits of the Capabilities System

### 1. Clean Code
**Before v2.2.0:**
```python
if self.is_redis_backend:
    self.storage.set_metadata(metadata)
else:
    self.metadata.set_metadata(metadata)
```

**After v2.2.0:**
```python
# Unified interface!
self._set_metadata(metadata)
```

The `_set_metadata()` helper checks capabilities internally:
```python
def _set_metadata(self, metadata):
    if self.capabilities.supports_metadata:
        return self.storage.set_metadata(metadata)  # Redis
    else:
        return self.metadata.set_metadata(metadata)  # SQLite
```

### 2. Automatic Optimization

KeyValueStore automatically chooses the best strategy:

```python
def set(self, key, value, tags=None):
    with self._get_lock(key):
        if self.use_buffering:  # Set based on capabilities
            self._buffered_set(key, value, tags)  # Filesystem
        else:
            self._immediate_set(key, value, tags)  # Redis
```

### 3. Easy Extensibility

Want to add a PostgreSQL backend? Just implement `get_capabilities()`:

```python
class PostgreSQLStorage(StorageBackend):
    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=False,      # Database is fast
            supports_native_ttl=False,     # No native TTL
            supports_transactions=True,    # ACID transactions!
            supports_metadata=True,        # JSONB columns for metadata
            write_strategy="immediate",
            is_distributed=True,
            is_persistent=True,
            supports_compression=True,
            supports_native_queries=True,  # Full SQL queries!
            max_value_size_bytes=1_000_000_000  # 1GB limit
        )
```

No changes needed to `KeyValueStore`! It automatically adapts.

## Under the Hood: The Implementation

Let's trace how capabilities work in the code.

### Initialization

```python
# From nakv.py - KeyValueStore.__init__ (v2.2.0)
class KeyValueStore:
    def __init__(self, ..., storage_backend="fs"):
        # 1. Create storage backend
        self.storage = StorageFactory.create_storage(storage_backend, ...)

        # 2. Query capabilities (NEW in v2.2.0)
        self.capabilities = self.storage.get_capabilities()

        # 3. Determine buffering strategy from capabilities
        self.use_buffering = (
            self.capabilities.supports_buffering and
            self.capabilities.write_strategy != "immediate"
        )

        # 4. Setup metadata based on capabilities
        if not self.capabilities.supports_metadata:
            # Backend doesn't handle metadata - use SQLite
            self.metadata = KeyValueMetadata(f'{db}_meta.db', ...)
        else:
            # Backend handles metadata natively
            self.metadata = None
```

### Write Strategies

```python
# From nakv.py - Unified write methods (v2.2.0)
def _buffered_set(self, key, value, tags=None, ttl=None):
    """Buffered write - for filesystem backend."""
    # Add to memory buffer
    with self.buffer_lock:
        self.buffer[key] = value
        self.current_buffer_size += len(value)

    # Update metadata
    self._set_metadata({"key": key, "size": len(value), "tags": tags, "ttl": ttl})

    # Check if buffer needs flushing
    self.flush_if_needed()

def _immediate_set(self, key, value, tags=None, ttl=None):
    """Immediate write - for Redis backend."""
    # Compress if needed
    data = self._compress_data(value)

    # Write directly to storage
    self.storage.write_data(path, data)

    # Update metadata
    self._set_metadata({"key": key, "size": len(value), "tags": tags, "ttl": ttl})
```

### Unified Metadata Interface

```python
# From nakv.py - Metadata helpers (v2.2.0)
def _set_metadata(self, metadata):
    """Set metadata - works with all backends."""
    if self.capabilities.supports_metadata:
        return self.storage.set_metadata(metadata)  # Backend handles it
    else:
        return self.metadata.set_metadata(metadata)  # Use SQLite

def _get_metadata(self, key):
    """Get metadata - works with all backends."""
    if self.capabilities.supports_metadata:
        return self.storage.get_metadata(key, self.db, self.namespace)
    else:
        return self.metadata.get_metadata(key, self.db, self.namespace)
```

## Practical Example: Comparing Backends

Let's see how the same code works differently with different backends:

```python
from nadb import KeyValueStore, KeyValueSync
import atexit

kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()
atexit.register(kv_sync.sync_exit)

# Backend 1: Filesystem
fs_store = KeyValueStore(
    data_folder_path="./fs_data",
    db="test_db",
    namespace="default",
    buffer_size_mb=1,
    sync=kv_sync,
    storage_backend="fs"
)

print(f"FS Backend - use_buffering: {fs_store.use_buffering}")
# Output: True
print(f"FS Backend - has metadata: {fs_store.metadata is not None}")
# Output: True (uses SQLite)

# Same operation
fs_store.set("user:1", b"Alice", tags=["user"])
# Internally: Adds to buffer, updates SQLite metadata, checks flush

# Backend 2: Redis
redis_store = KeyValueStore(
    data_folder_path="./redis_data",
    db="test_db",
    namespace="default",
    buffer_size_mb=1,  # Ignored
    sync=kv_sync,
    storage_backend="redis"
)

print(f"Redis Backend - use_buffering: {redis_store.use_buffering}")
# Output: False
print(f"Redis Backend - has metadata: {redis_store.metadata is not None}")
# Output: False (Redis handles metadata)

# Same operation
redis_store.set("user:1", b"Alice", tags=["user"])
# Internally: Writes directly to Redis, stores metadata in Redis hash
```

## Conclusion

The **Backend Capabilities System** (v2.2.0) represents a major architectural improvement in NADB. Instead of scattered conditional checks (`if self.is_redis_backend:`), each backend now *declares its capabilities*, and `KeyValueStore` *automatically adapts*.

This brings:
- **Cleaner code**: Unified interfaces replace conditionals
- **Better performance**: Each backend uses its optimal strategy
- **Easy extensibility**: New backends integrate seamlessly
- **Consistent behavior**: Same API, optimized execution

When you use NADB now, you don't need to worry about backend differences. Whether you're using filesystem for simplicity, Redis for speed, or (in the future) PostgreSQL for power - the API remains identical, and NADB ensures optimal performance for each backend.

Ready to learn more advanced features? Check out [Chapter 9: Transactions](09_transactions_.md) for ACID guarantees, [Chapter 10: Backup & Recovery](10_backup_recovery_.md) for data protection, or [Chapter 11: Indexing & Caching](11_indexing_caching_.md) for query optimization!

---
