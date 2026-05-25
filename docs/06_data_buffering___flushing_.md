# Buffering And Flushing

Filesystem stores use an in-memory buffer to batch writes. Redis stores write immediately because Redis does not benefit from NADB's local file buffer.

```python
store.set("key", b"value")
store.flush()
```

`flush()` writes pending buffered values to the backend. `KeyValueSync` can call `flush_if_needed()` periodically.

Buffered metadata is created when `set()` is called, then updated with stored size and checksum details after the value is flushed. Reads check the buffer first, so newly written values are available immediately.

TTL writes use immediate persistence so expiration starts predictably.

`flushdb(confirm=True, scope="namespace")` clears data explicitly. Supported scopes are `namespace`, `db`, and `all`; calls without `confirm=True` still work for compatibility but emit a warning.
