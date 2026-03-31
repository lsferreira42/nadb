# Chapter 5: Storage Backends & Compression

NADB achieves its flexibility by decoupling the high-level `KeyValueStore` features (Transactions, Indexing, Logging, Backup) from low-level data storage through specialized **Storage Backends**. 

Every storage backend extends the abstract base class `StorageBackend` and implements common tasks like writing, reading, deleting data files or keys, getting size limits, and managing path logic.

NADB relies heavily on the **Capabilities Architecture** (see Chapter 13) to determine the behavior around buffering and data flushing depending on what the selected storage backend natively optimally supports.

---

## 💾 Available Storage Backends

### 1. `FileSystemStorage` (`fs`, Default)
The `FileSystemStorage` uses the local disk array to maintain persistence.

**Key Features:**
*   **Hierarchical Location Strategy:** It splits keys up using `blake2b` hashes (e.g. `path/to/db/a3/b4/a3b4...hash`) to ensure thousands of keys don't clutter a single disk directory.
*   **Buffered Writes Strategy:** Because direct individual disk writes are expensive, `fs` uses the `KeyValueStore.use_buffering = True` logic. Data is aggregated in-memory and committed asynchronously in batched threads during `flush_to_disk()`.
*   **Atomic Rename Operations:** During flushing, actual files are written to safe temporary files (`.nadb_temp...`) before executing a POSIX-atomic renaming operation (`os.rename()`). This inherently prevents data corruption related to half-written files.
*   **Path Traversal Protections:** Resolves exact absolute paths natively stopping directory escape bugs (`../../etc/passwd`).

### 2. `RedisStorage` (`redis` plugin)
The `RedisStorage` relies on an active Redis server to maintain state, beneficial for scaling out the service over the network. 

**Key Features:**
*   **Connection Pooling Mechanism:** Built into NADB is a high-concurrency robust `ConnectionPool` engine configuring `redis.Redis(connection_pool=...)` behind scenes.
*   **Immediate Writing Strategy:** Redis operations are lightweight memory updates. The `KeyValueStore` disables its internal buffering lock here and delegates direct data writes to Redis continuously.
*   **Native TTL Supported:** Expiration commands translate directly to Redis' internal `EXPIRE` methods.
*   **Native Metadata Structures:** Uses Redis Hashes (`HSET`/`HGETALL`) instead of relying on local SQLite databases for tracking properties like keys size and tags, significantly enhancing clustered application deployments.

*Note: Requires `pip install nadb[redis]` to initialize.*

---

## 🗜️ Data Compression (`zlib`)

Both backends include first-class operations to shrink data storage requirements via `compression_enabled` passed directly to the `KeyValueStore` constructor. 

```python
# Instantiating KeyValueStore with built-in compression
kv_store = KeyValueStore(
    storage_backend="fs", 
    compression_enabled=True,
    data_folder_path="./data",
    ...
)
```

**How it Works:**
1.   Whenever `KeyValueStore` executes a `set()`, it performs a condition check over the minimum configured compression threshold (`COMPRESS_MIN_SIZE` defaults). Small payloads are kept verbatim to eliminate unneeded CPU burning.
2.   Eligible data is zipped up using Python's native `zlib` standard library.
3.   A `CMP:` header prefix is pushed upfront to the binary record payload indicating to NADB read methods that the record carries compressed assets on reading paths.

This system creates highly significant storage savings when storing sizable byte blocks (like JSON models, long strings, binary document dumps).

---
**Next up:** [Data Buffering & Flushing](06_data_buffering___flushing_.md)
