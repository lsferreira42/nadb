# Storage Backends

NADB ships with filesystem, Redis, memory, SQLite, and S3-compatible backends. All store bytes and expose the same storage interface to `KeyValueStore`.

## Filesystem

```python
store = KeyValueStore(
    data_folder_path="./data",
    db="app",
    namespace="dev",
    storage_backend="fs",
)
```

Filesystem storage:

- writes files with atomic temp-file replacement,
- uses owner-only permissions by default,
- checks paths with symlink-aware real paths,
- stores metadata in SQLite,
- benefits from buffered writes.

## Redis

```python
store = KeyValueStore(
    db="app",
    namespace="prod",
    storage_backend="redis",
    storage_options={
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "password": None,
        "key_prefix": "myapp:nadb",
        "max_connections": 20,
    },
)
```

Redis storage:

- writes immediately,
- uses Redis hashes for metadata,
- uses native TTL where available,
- uses connection pooling,
- uses SCAN iteration in production paths,
- supports a configurable key prefix for shared Redis databases.

## Memory

`storage_backend="memory"` keeps data and metadata in process memory. It is useful for fast tests and ephemeral workloads.

## SQLite

`storage_backend="sqlite"` stores values and metadata in a single SQLite file with WAL mode.

## S3-Compatible

`storage_backend="s3"` uses `boto3` when available. Without `boto3`, it uses a local bucket-shaped fallback for development and tests.

## Compression

NADB compresses values larger than the compression threshold when compression is enabled. New compressed records use a versioned NADB binary envelope. Legacy `CMP:` records remain readable for backward compatibility.

## Metadata

Metadata records can include:

- `value_type`
- `encoding`
- `content_type`
- `logical_size`
- `stored_size`
- `checksum`
- `ttl`
- `expires_at`
- `tags`
