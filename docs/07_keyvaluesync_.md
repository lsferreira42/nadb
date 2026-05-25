# KeyValueSync

`KeyValueSync` runs a background thread that periodically flushes registered stores and cleans expired filesystem records.

```python
from nadb import KeyValueSync, KeyValueStore

sync = KeyValueSync(flush_interval_seconds=5)
sync.start()

store = KeyValueStore("./data", "app", 1, "dev", sync)

sync.sync_exit()
```

If no sync is provided, `KeyValueStore` creates one for itself and stops it in `close()`.

```python
with KeyValueStore.open(data_folder_path="./data", db="app") as store:
    store.set_text("hello", "world")
```

Use `status()` to inspect the background worker.

Expiration cleanup emits `expire` watcher events for removed keys.
