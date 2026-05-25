# KeyValueStore

`KeyValueStore` is the main NADB API. It stores values by string key, persists them through a storage backend, and maintains metadata for tags, TTL, type, size, checksum, and timestamps.

In `0.3.0`, `KeyValueStore` also supports `return_type`, `StoredValue`, batch operations, CAS writes, conditional writes, counters, hooks, watchers, streaming, chunked blobs, backup streams, and optional encryption.

## Opening a store

```python
from nadb import KeyValueStore, open_store

store = KeyValueStore(
    data_folder_path="./data",
    db="app",
    namespace="dev",
    storage_backend="fs",
)

store.close()
```

For applications, prefer the context manager:

```python
with open_store(data_folder_path="./data", db="app", namespace="dev") as store:
    store.set_text("message", "hello")
```

If `sync` is omitted, NADB creates and owns a default `KeyValueSync`.

## Value types

`set()` accepts:

- `str`
- `bytes`
- `bytearray`
- `memoryview`

`get()` always returns bytes for compatibility. Use the typed helpers when you want decoded data.

```python
store.set("raw", b"\x00\x01")
store.set("title", "Hello")

assert store.get("title") == b"Hello"
assert store.get_text("title") == "Hello"
```

## Typed helpers

```python
store.set_text("name", "Alice", tags=["user"])
store.set_bytes("avatar", b"\x89PNG...", tags=["asset"])
store.set_json("settings", {"theme": "dark"}, tags=["config"])

store.get_text("name")
store.get_bytes("avatar")
store.get_json("settings")
```

## Return Types

```python
store = KeyValueStore(return_type="stored")
store.set_text("message", "hello")
value = store.get("message")
assert value.text == "hello"
assert value.etag == value.metadata["checksum"]
```

Use `return_type="bytes"` for backward-compatible byte reads, `return_type="str"` for decoded text reads, and `return_type="stored"` for a rich `StoredValue`.

## Batch, CAS, And Conditional Writes

```python
store.set_many({"a": "1", "b": "2"})
store.get_many(["a", "b"])
store.exists_many(["a", "missing"])

etag = store.get_with_metadata("a")["metadata"]["checksum"]
store.compare_and_set("a", etag, "3")
store.set_if_absent("lock", "owner")
store.set_if_exists("lock", "new-owner")
store.incr("counter")
store.decr("counter")
```

## Hooks And Events

```python
store.watch("*", lambda **event: print(event["event"], event["key"]))
store.add_validator(lambda key, value, meta: None)
store.add_transformer(lambda key, value, meta: value.strip())
```

NADB stores `value_type`, `encoding`, `content_type`, `logical_size`, `stored_size`, and `checksum` in metadata.

## Optional reads

```python
store.get_or_none("missing")
store.get_or_default("missing", b"default")
store.exists("name")
```

`get()` still raises `KeyError` for missing keys.

## Backend options

```python
store = KeyValueStore(
    db="sessions",
    namespace="prod",
    storage_backend="redis",
    storage_options={
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "key_prefix": "myapp:nadb",
    },
)
```

Backend loading is strict by default. Use `allow_backend_fallback=True` only when falling back to filesystem is intentional.
