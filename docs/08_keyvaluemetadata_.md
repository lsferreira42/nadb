# Metadata

Metadata describes each stored key. Filesystem stores keep metadata in SQLite. Redis stores metadata in Redis hashes.

Important fields:

- `path`
- `key`
- `db`
- `namespace`
- `created_at`
- `last_updated`
- `last_accessed`
- `size`
- `logical_size`
- `stored_size`
- `value_type`
- `encoding`
- `content_type`
- `checksum`
- `encrypted`
- `ttl`
- `expires_at`
- `tags`

`schema_version` is maintained in SQLite metadata stores so additive metadata migrations can run idempotently.

```python
record = store.get_with_metadata("profile:1")
value = record["value"]
metadata = record["metadata"]
```

Metadata queries power tags, backup selection, statistics, and expiration cleanup. The public store methods use a unified metadata interface so application code does not need to know where metadata is stored.
