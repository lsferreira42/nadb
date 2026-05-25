# TTL

TTL sets an expiration time for a key.

```python
store.set_with_ttl("session:abc", "logged-in", ttl_seconds=3600, tags=["session"])

remaining = store.ttl("session:abc")
```

`0.3.0` adds absolute and `timedelta` helpers:

```python
store.set_with_expires_at("session", "data", datetime.now() + timedelta(hours=1))
store.set_with_timedelta("job", "queued", timedelta(minutes=15))
store.persist_ttl("job")
```

Behavior depends on backend capabilities:

- Redis uses native expiration.
- Filesystem stores `ttl` and `expires_at` in metadata, and `KeyValueSync` periodically cleans expired records.

`ttl(key)` returns:

- an integer number of remaining seconds for expiring keys,
- `None` for persistent keys,
- `KeyError` if the key does not exist.

Transactions and restores preserve remaining TTL where metadata is available, so rollback does not restart an old expiration window unnecessarily.
