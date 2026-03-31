# Chapter 4: Storage Factory

The `StorageFactory` is an implementation of the Factory Design Pattern used in NADB to dynamically instantiate and manage different storage backends. This allows the system to remain decoupled from the specific storage mechanism logic, making the `KeyValueStore` highly extensible.

## 🏭 How StorageFactory Works

When you initialize a `KeyValueStore`, it uses the `StorageFactory` internally to load the requested backend. 

```python
from nadb import KeyValueStore

# The StorageFactory automatically loads `FileSystemStorage`
kv_store = KeyValueStore(storage_backend="fs", data_folder_path="./data", ...)

# The StorageFactory automatically loads `RedisStorage`
kv_redis = KeyValueStore(storage_backend="redis", ...)
```

The factory pattern implementation handles:
1. **Dynamic Module Loading:** Imports the specific backend matching the `storage_backend` type string without having all modules hardcoded, enabling pluggable backends.
2. **Error Recovery (Fallback mechanism):** Automatically falls back to the default `fs` (Filesystem) backend if a requested backend module (like `redis`) fails to load.
3. **Keyword Expansion:** Passes arbitrary kwargs (like `base_path`) seamlessly down to the instantiated driver.

## 🛠 Adding Custom Storage Backends

Thanks to the `StorageFactory`, adding a new backend requires ZERO changes to the core `KeyValueStore` code. The factory expects that a new backend:
1. Exists inside the `storage_backends` package.
2. Returns an object mapping to the name correctly (e.g. `MemcacheStorage` for `"memcache"`).
3. Inherits from `StorageBackend` and implements the expected `BackendCapabilities` methods.

### Example Internal Usage

```python
from storage_backends import StorageFactory

# Creates a Redis storage backend instance
redis_backend = StorageFactory.create_storage("redis", base_path="./data")
```

Under the hood, if `redis` is passed, the factory dynamically imports `storage_backends.redis` and invokes the `RedisStorage` class constructor.

---
**Next up:** [Storage Backends (FileSystemStorage, RedisStorage)](05_storage_backends__filesystemstorage__redisstorage__.md)
