# NADB

NADB is a Python key-value store for application data that needs more than a dictionary: persistence, tags, TTL, transactions, backups, indexing, typed values, streaming, optional encryption, and multiple storage backends.

[![Tests](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml/badge.svg)](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/lsferreira42/nadb/branch/main/graph/badge.svg)](https://codecov.io/gh/lsferreira42/nadb)

Current release: `0.3.0`

## Highlights

- Text, bytes, JSON, `bytearray`, and `memoryview` values.
- `StoredValue` return mode with bytes, text, metadata, content type, TTL, and ETag/checksum.
- Backends: filesystem, Redis, in-memory, SQLite, and S3-compatible object storage.
- Hierarchical namespaces and paginated key scanning.
- Batch operations, conditional writes, compare-and-set, counters, and touch.
- TTL by seconds, `datetime`, or `timedelta`, plus `persist_ttl()`.
- Query builder, custom secondary indexes, ordering, filtering, and tag queries.
- Watchers/events, validation hooks, and transformation hooks.
- Optional at-rest encryption envelope.
- Streaming readers/writers and chunked blobs for large binary values.
- Full, incremental, JSONL stream, and tar backup exports with retention pruning.
- CLI: `nadb set/get/keys/tags/export/import/compact/verify/cleanup-expired`.
- Optional OpenTelemetry spans plus lightweight built-in operation counters.
- Safer behavior: strict backend loading, checksums, redacted logs, owner-only filesystem permissions, Redis SCAN paths.

## Install

```bash
pip install nadb
```

Optional extras:

```bash
pip install "nadb[redis]"
pip install "nadb[s3]"
pip install "nadb[otel]"
pip install "nadb[dev,redis]"
```

## Quick Start

```python
from nadb import open_store

with open_store(data_folder_path="./data", db="app", namespace="prod") as store:
    store.set_text("user:1:name", "Alice", tags=["user"])
    store.set_json("user:1:settings", {"theme": "dark"}, tags=["config"])
    store.set_bytes("user:1:avatar", b"\x89PNG...", tags=["asset"])

    assert store.get_text("user:1:name") == "Alice"
    assert store.get_json("user:1:settings") == {"theme": "dark"}
```

## Rich Values

```python
from nadb import KeyValueStore

store = KeyValueStore(return_type="stored")
store.set_text("message", "hello")

value = store.get("message")
assert value.text == "hello"
print(value.content_type, value.etag, value.metadata)
```

## Backends

```python
KeyValueStore(storage_backend="fs", data_folder_path="./data")
KeyValueStore(storage_backend="memory")
KeyValueStore(storage_backend="sqlite", storage_options={"database_name": "app.sqlite3"})
KeyValueStore(storage_backend="redis", storage_options={"host": "localhost", "key_prefix": "myapp:nadb"})
KeyValueStore(storage_backend="s3", storage_options={"bucket": "my-bucket", "prefix": "nadb"})
```

S3 uses `boto3` when installed. Without `boto3`, it uses a local S3-shaped development fallback.

## Data Operations

```python
store.set_many({"a": "1", "b": "2"})
store.get_many(["a", "b"])
store.exists_many(["a", "missing"])
store.delete_many(["a", "b"])

etag = store.get_with_metadata("key")["metadata"]["checksum"]
store.compare_and_set("key", etag, "new-value")
store.set_if_absent("lock", "owner")
store.set_if_exists("lock", "new-owner")
store.incr("counter")
store.decr("counter")
```

## TTL

```python
from datetime import datetime, timedelta

store.set_with_ttl("cache:item", "fresh", ttl_seconds=60)
store.set_with_expires_at("session", "data", datetime.now() + timedelta(hours=1))
store.set_with_timedelta("job", "queued", timedelta(minutes=15))
store.ttl("job")
store.persist_ttl("job")
```

## Querying

```python
store.set_json("user:1", {"status": "active", "plan": "pro"}, tags=["user"])
store.create_index("status")

active_keys = store.query_index("status", "active")
query_keys = store.query().tag("user").where("content_type", "application/json").limit(50).keys()
pages = list(store.scan_keys(prefix="user:", page_size=100))
```

## Hooks, Events, Encryption

```python
store = KeyValueStore(encryption_key="local-secret")

store.watch("*", lambda **event: print(event["event"], event["key"]))
store.add_validator(lambda key, value, meta: None)
store.add_transformer(lambda key, value, meta: value.strip())
```

## Large Values

```python
with store.open_writer("video:raw", chunk_size=1024 * 1024) as writer:
    writer.write(b"...large payload...")

payload = store.get_chunked("video:raw")
```

## Backups

```python
backup = store.create_backup("daily")
store.create_incremental_backup(backup.backup_id, "daily-inc")
store.export_backup_stream("backup.jsonl")
store.export_backup_tar("backup.tar")
store.prune_backups(keep_last=10, keep_days=30)
```

## CLI

```bash
nadb --data ./data --db app --namespace prod set hello world
nadb --data ./data --db app --namespace prod get hello
nadb --data ./data --db app --namespace prod keys
nadb --data ./data --db app --namespace prod export backup.jsonl
```

## Testing

```bash
make test
make test-advanced
make test-redis      # requires Redis
make test-all        # requires Redis
```

Redis tests skip when Redis is unavailable unless `NADB_REQUIRE_REDIS=1` is set.

## Documentation

See [docs/index.md](docs/index.md).

## License

MIT. See [LICENSE](LICENSE).
