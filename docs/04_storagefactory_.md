# StorageFactory

`StorageFactory` creates storage backend instances by name.

```python
from storage_backends import StorageFactory

fs = StorageFactory.create_storage("fs", base_path="./data")
```

Built-in backends in `0.3.0`: `fs`, `redis`, `memory`, `sqlite`, and `s3`.

`KeyValueStore` uses the factory internally:

```python
store = KeyValueStore(storage_backend="redis", storage_options={"host": "localhost"})
```

## Fallback policy

Backend fallback is disabled by default. If a backend cannot be imported or initialized, NADB raises `ValueError` instead of silently writing to a different backend.

```python
store = KeyValueStore(
    storage_backend="custom_backend",
    allow_backend_fallback=True,
)
```

Use fallback only for development or explicit migration workflows.

## Adding a backend

Implement `StorageBackend`, expose `get_capabilities()`, and either add the backend to the factory map or follow the naming convention:

- module: `storage_backends/my_backend.py`
- class: `MyBackendStorage`
