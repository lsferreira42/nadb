# Transactions

Transactions collect operations and commit them as a unit from the caller's perspective. If commit fails or the context exits with an error, NADB rolls back previous values.

```python
with store.transaction() as tx:
    tx.set("user:1", b"Alice", ["user"])
    tx.set("profile:1", b"{}", ["profile"])
```

Supported transaction operations:

- `set(key, value, tags=None)`
- `set_with_ttl(key, value, ttl_seconds, tags=None)`
- `delete(key)`
- `batch_set(items)`
- `batch_delete(keys)`

Rollback restores:

- original value,
- original tags,
- remaining TTL when available,
- deleted keys.

Transactions do not replace backend-native distributed transaction guarantees. They are an application-level rollback mechanism around NADB operations.

`set_many(..., atomic=True)` and `delete_many(..., atomic=True)` use the same transaction manager.
