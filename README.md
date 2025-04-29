# NADB - Not A Database

A simple, thread-safe, zero external dependencies key-value store with asynchronous memory buffering capabilities and disk persistence.

[![Tests](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml/badge.svg)](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/lsferreira42/nadb/branch/main/graph/badge.svg)](https://codecov.io/gh/lsferreira42/nadb)

> For more details and comprehensive documentation, please refer to the  
> [NADB Tutorial/Docs](https://github.com/lsferreira42/nadb/blob/main/docs/index.md).

## Features

- Thread-safe operations for setting, getting, and deleting key-value pairs.
- In-memory buffering of key-value pairs with asynchronous flushing to disk.
- Periodic flushing of the buffer to disk to ensure data integrity.
- Manual flushing capability for immediate persistence.
- Namespace and database separation for organized data storage.
- Simple usage and minimal setup required.
- **NEW:** Support for any file type (binary data storage)
- **NEW:** Tag system for organizing and querying data
- **NEW:** Data compression for efficient storage
- **NEW:** TTL (Time To Live) for automatic data expiration
- **NEW:** Performance metrics and monitoring
- **NEW:** Storage compaction for optimizing disk usage
- **NEW:** Pluggable storage backends

## Installation

```bash
# Basic installation
pip install nadb

# Installation with Redis support
pip install nadb[redis]
```

The basic installation includes only the filesystem backend. If you want to use the Redis backend, you need to install the package with Redis support as shown above.

## Quickstart

Here's a basic example of how to use NADB:

```python
from nadb import KeyValueStore, KeyValueSync

# Create a KeyValueStore instance

data_folder_path = './data'
db_name = 'db1'
buffer_size_mb = 1  # 1 MB
flush_interval_seconds = 60  # 1 minute
namespace = 'namespace1'

# Initialize the KeyValueSync for asynchronous flushing
kv_sync = KeyValueSync(flush_interval_seconds)
kv_sync.start()  # Start the synchronization thread

# Initialize the KeyValueStore with compression enabled
kv_store = KeyValueStore(
    data_folder_path=data_folder_path, 
    db=db_name, 
    buffer_size_mb=buffer_size_mb, 
    namespace=namespace, 
    sync=kv_sync,
    compression_enabled=True,
    storage_backend="fs"  # Use the filesystem storage backend
)

# Store text data with tags
text_data = "Hello, world!".encode('utf-8')
kv_store.set("text_key", text_data, tags=["text", "greeting"])

# Store binary data (any type of file)
with open("image.png", "rb") as f:
    binary_data = f.read()
kv_store.set("image_key", binary_data, tags=["binary", "image"])

# Store data with TTL (expiration)
ttl_data = "This will expire".encode('utf-8')
kv_store.set_with_ttl("temporary_key", ttl_data, ttl_seconds=3600, tags=["temporary"])

# Get a value
text_value = kv_store.get("text_key")  # Returns bytes that can be decoded: text_value.decode('utf-8')

# Get a value with metadata
result = kv_store.get_with_metadata("image_key")
print(f"Image size: {result['metadata']['size']} bytes, tags: {result['metadata']['tags']}")

# Query by tags
image_keys = kv_store.query_by_tags(["image"])
print(f"All image keys: {image_keys}")

# List all tags
all_tags = kv_store.list_all_tags()
print(f"All tags in store: {all_tags}")

# Delete a key-value pair
kv_store.delete("text_key")

# Get performance statistics
stats = kv_store.get_stats()
print(f"Total items: {stats['count']}")
print(f"Buffer utilization: {stats['buffer_utilization_percent']:.2f}%")
print(f"Operations: {stats['performance']['operations']}")

# Run storage compaction
compaction_results = kv_store.compact_storage()
print(f"Compaction results: {compaction_results}")

# Manual flush (optional, as flushing occurs automatically based on buffer size and time interval)
kv_store.flush()

# Stop the synchronization process and exit
kv_sync.sync_exit()
```

## Advanced Features

### Tag System

NADB allows you to associate tags with your key-value pairs, making organization and retrieval more flexible:

```python
# Store with multiple tags
kv_store.set("user:123", user_data, tags=["user", "premium", "active"])

# Query by one or more tags (all tags must match)
premium_users = kv_store.query_by_tags(["user", "premium"])
```

### Binary Data Storage

NADB now supports storing any type of binary data. This is perfect for images, documents, or any other file type:

```python
# Store an image
with open("large_image.jpg", "rb") as f:
    image_data = f.read()
kv_store.set("image:profile", image_data, tags=["image", "profile"])

# Store a PDF document
with open("document.pdf", "rb") as f:
    pdf_data = f.read()
kv_store.set("document:contract", pdf_data, tags=["document", "contract"])
```

### TTL (Time To Live)

Automatically expire data after a specified time:

```python
# This data will automatically be removed after 1 hour
kv_store.set_with_ttl("session:token", token_data, ttl_seconds=3600, tags=["session"])
```

### Compression

NADB automatically compresses large data to save disk space:

```python
# Enable compression when creating the store
kv_store = KeyValueStore(..., compression_enabled=True)

# Run manual compaction to optimize existing data
compaction_results = kv_store.compact_storage()
```

### Storage Backends

NADB supports pluggable storage backends to store your data in different systems:

```python
# Use the default filesystem backend
kv_store = KeyValueStore(..., storage_backend="fs")

# Use Redis as a distributed storage backend (requires 'redis' package)
kv_store = KeyValueStore(
    data_folder_path=data_folder_path, 
    db=db_name, 
    buffer_size_mb=buffer_size_mb, 
    namespace=namespace, 
    sync=kv_sync,
    compression_enabled=True,
    storage_backend="redis"
)
```

#### Redis Backend Configuration

When using the Redis backend, the Redis connection parameters are handled by the storage backend. The Redis backend defaults to connecting to `localhost:6379` with database `0`. To customize Redis connection parameters, you need to modify the `StorageFactory` call or the `RedisStorage` initialization.

**Option 1:** Create a wrapper function for custom configurations:

```python
def create_redis_kv_store(data_folder_path, db, buffer_size_mb, namespace, sync, 
                          redis_host='localhost', redis_port=6379, redis_db=0, redis_password=None):
    """Create a KeyValueStore with Redis backend with custom Redis parameters."""
    from storage_backends.redis import RedisStorage
    
    # Create custom Redis storage
    redis_storage = RedisStorage(
        base_path=data_folder_path,
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=redis_password
    )
    
    # Create KeyValueStore with the custom Redis storage
    kv_store = KeyValueStore(
        data_folder_path=data_folder_path,
        db=db,
        buffer_size_mb=buffer_size_mb,
        namespace=namespace,
        sync=sync,
        compression_enabled=True,
        storage_backend="redis"
    )
    
    # Replace the default Redis storage with our custom one
    kv_store.storage = redis_storage
    
    return kv_store

# Usage
kv_store = create_redis_kv_store(
    data_folder_path='./data',
    db='my_db',
    buffer_size_mb=1,
    namespace='my_namespace',
    sync=kv_sync,
    redis_host='redis.example.com',
    redis_port=6380,
    redis_db=5,
    redis_password='secret'
)
```

**Note:** The Redis backend differs from filesystem storage in its handling of data:

1. Data is written to Redis immediately, rather than being kept in the buffer
2. TTL is implemented using Redis's native expiration mechanism
3. Tags are implemented using Redis sets for efficient querying

To implement your own storage backend, create a class in the `storage_backends` directory that implements the required interface methods (see `fs.py` and `redis.py` for examples).

### Performance Metrics

Monitor the performance and usage of your database:

```python
# Get detailed statistics
stats = kv_store.get_stats()
print(f"Read operations: {stats['performance']['operations'].get('get', {}).get('count', 0)}")
print(f"Average read time: {stats['performance']['operations'].get('get', {}).get('avg_ms', 0):.2f} ms")
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Development

### Continuous Integration

This project uses GitHub Actions for continuous integration. Every push to the main branch and every pull request will trigger the test suite to run against multiple Python versions.

### Running Tests

Para rodar os testes localmente:

```bash
# Rodar todos os testes
make test-all

# Rodar testes com relatório de cobertura
make test-cov

# Rodar apenas testes do sistema de arquivos
make test-fs

# Rodar apenas testes do Redis
make test-redis
```

### Redis Tests

Os testes do Redis **necessitam de um servidor Redis rodando** em `localhost:6379`. Se o Redis não estiver disponível, os testes **falharão** (diferente das versões anteriores onde os testes eram pulados).

Para instalar o Redis:

- **macOS**: `brew install redis && brew services start redis`
- **Ubuntu/Debian**: `sudo apt-get install redis-server && sudo systemctl start redis`
- **Windows**: Instale via WSL ou use o Chocolatey

Você pode rodar os testes do Redis com:

```bash
make test-redis
```

## Development

Para contribuir com o desenvolvimento do pacote:

1. Clone o repositório
2. Instale as dependências de desenvolvimento:
   ```bash
   pip install -e ".[dev]"
   ```
3. Para suporte a Redis, instale:
   ```bash
   pip install -e ".[redis]"
   ```
4. Para todos os extras:
   ```bash
   pip install -e ".[dev,redis]"
   ```
