# Backend Capabilities

Each storage backend describes its behavior through `BackendCapabilities`.

```python
BackendCapabilities(
    supports_buffering=True,
    supports_native_ttl=False,
    supports_transactions=False,
    supports_metadata=False,
    supports_atomic_writes=True,
    write_strategy="buffered",
    is_distributed=False,
    is_persistent=True,
    supports_compression=True,
    supports_native_queries=False,
    max_value_size_bytes=None,
)
```

`KeyValueStore` uses capabilities to choose behavior:

- filesystem supports buffering and uses SQLite metadata,
- Redis writes immediately and stores metadata natively,
- Redis supports native TTL,
- distributed backends skip local compaction.

New backends should implement `StorageBackend`, return accurate capabilities, and avoid requiring backend-specific conditionals in `KeyValueStore`.

`is_redis_backend` remains as a deprecated compatibility attribute, but internal production code should prefer capabilities.

New `0.3.0` backends use the same capability model:

- `memory`: immediate, metadata-native, non-persistent.
- `sqlite`: immediate, metadata-native, persistent.
- `s3`: immediate, object-store oriented, local fallback when `boto3` is unavailable.
