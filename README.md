# NADB - Not A Database

A simple, thread-safe, zero external dependencies key-value store with asynchronous memory buffering capabilities and disk persistence.

[![Tests](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml/badge.svg)](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/lsferreira42/nadb/branch/main/graph/badge.svg)](https://codecov.io/gh/lsferreira42/nadb)

:rotating_light: **This project is educational and not intended for production use.** :rotating_light:


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
image_data, metadata = kv_store.get_with_metadata("image_key")
print(f"Image size: {metadata['size']} bytes, tags: {metadata['tags']}")

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
print(f"Total items: {stats['total_items']}")
print(f"Buffer utilization: {stats['buffer_utilization_percent']:.2f}%")
print(f"Operations: {stats['metrics']['operations']}")

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
    storage_backend="redis", 
    host="localhost",     # Redis host
    port=6379,            # Redis port 
    db=0,                 # Redis database number
    password=None         # Redis password if required
)

# In the future, additional backends like Memcached may be supported:
# kv_store = KeyValueStore(..., storage_backend="memcache")
```

#### Redis Backend Features

The Redis backend provides several advantages for distributed applications:

- **Fully distributed storage**: Both data and metadata are stored in Redis, making it ideal for clustered applications
- **High performance**: Redis's in-memory nature provides very fast read/write operations
- **Automatic failover**: Can be used with Redis Sentinel or Redis Cluster for high availability
- **Built-in TTL support**: Uses Redis's sorted sets for efficient TTL management
- **Tag-based queries**: Leverages Redis sets for efficient tag querying

To use the Redis backend, first install the required dependency:

```bash
pip install redis
```

Then initialize your KeyValueStore with `storage_backend="redis"` and any Redis connection parameters.

To implement your own storage backend, create a class in the `storage_backends` directory that implements the required interface methods (see `fs.py` and `redis.py` for examples).

### Performance Metrics

Monitor the performance and usage of your database:

```python
# Get detailed statistics
stats = kv_store.get_stats()
print(f"Read operations: {stats['metrics']['operations'].get('read', {}).get('count', 0)}")
print(f"Average read time: {stats['metrics']['operations'].get('read', {}).get('avg_ms', 0):.2f} ms")
print(f"Data compression ratio: {stats['metrics']['compression_ratio']:.2f}x")
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Development

### Continuous Integration

This project uses GitHub Actions for continuous integration. Every push to the main branch and every pull request will trigger the test suite to run against multiple Python versions.

### Running Tests Locally

To run the tests locally:

```bash
# Run all tests
make test-all

# Run tests with coverage report
make test-cov

# Run only filesystem tests
make test-fs

# Run only Redis tests
make test-redis
```
