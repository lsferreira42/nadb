# NADB Documentation

NADB `0.3.0` adds a fuller application-data layer on top of the existing persistent key-value store.

## 0.3.0 Feature Set

- `return_type="bytes" | "str" | "stored"` and the `StoredValue` object.
- Hierarchical namespaces with namespace listing and confirmed namespace clearing.
- Batch operations: `set_many`, `get_many`, `delete_many`, `exists_many`.
- CAS and conditional writes: `compare_and_set`, `set_if_version`, `set_if_absent`, `set_if_exists`, `touch`.
- Atomic counters: `incr`, `decr`.
- TTL by seconds, `datetime`, and `timedelta`, plus `persist_ttl`.
- Paginated key scanning and prefix queries.
- Custom indexes over metadata and JSON fields.
- Fluent query builder.
- Sorted and filtered metadata queries.
- Watchers/events for writes, deletes, expiration, restore, and flush.
- Validation and transformation hooks.
- Optional at-rest encryption.
- SQLite, memory, and S3-compatible backends.
- Streaming readers/writers and chunked blob storage.
- JSONL/tar backup streams and backup retention pruning.
- Schema-version metadata migrations.
- CLI entry point: `nadb`.
- Optional OpenTelemetry spans and local operation counters.
- Configurable cache TTL and approximate cache memory caps.
- Explicit `flushdb(confirm=True, scope=...)` behavior.

## Quick Start

```python
from nadb import open_store

with open_store(data_folder_path="./data", db="app", namespace="dev") as store:
    store.set_text("hello", "world", tags=["example"])
    store.set_json("settings", {"theme": "dark"})
    store.set_bytes("blob", b"\x00\x01")

    assert store.get_text("hello") == "world"
```

## Chapters

1. [KeyValueStore](01_keyvaluestore_.md)
2. [Tags](02_tags_.md)
3. [TTL](03_ttl__time_to_live__.md)
4. [StorageFactory](04_storagefactory_.md)
5. [Storage Backends](05_storage_backends__filesystemstorage__redisstorage__.md)
6. [Buffering And Flushing](06_data_buffering___flushing_.md)
7. [KeyValueSync](07_keyvaluesync_.md)
8. [Metadata](08_keyvaluemetadata_.md)
9. [Transactions](09_transactions_.md)
10. [Backup And Recovery](10_backup_recovery_.md)
11. [Indexing And Caching](11_indexing_caching_.md)
12. [Structured Logging](12_structured_logging_.md)
13. [Backend Capabilities](13_backend_capabilities_system.md)

## Validation

```bash
make test
make test-advanced
make test-redis     # requires Redis
make test-all       # requires Redis
```
