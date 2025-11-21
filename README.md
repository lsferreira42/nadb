# NADB - Not A Database

A high-performance, enterprise-grade key-value store with advanced features including transactions, backup & recovery, intelligent indexing, and structured logging.

[![Tests](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml/badge.svg)](https://github.com/lsferreira42/nadb/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/lsferreira42/nadb/branch/main/graph/badge.svg)](https://codecov.io/gh/lsferreira42/nadb)

> For comprehensive documentation and tutorials, please refer to the  
> [NADB Documentation](https://github.com/lsferreira42/nadb/blob/main/docs/index.md).

## 🚀 Features

### Core Features
- **Thread-safe operations** for concurrent access
- **In-memory buffering** with asynchronous disk persistence
- **Binary data storage** for any file type
- **Tag system** for flexible data organization
- **TTL (Time To Live)** for automatic data expiration
- **Data compression** for efficient storage
- **Pluggable storage backends** (Filesystem, Redis)

### Advanced Features (Enterprise-Grade)
- **ACID Transactions** with automatic rollback (including tags and TTL restoration)
- **Backup & Recovery** with incremental backups
- **Intelligent Indexing & Caching** with TTL support for cache entries
- **Structured Logging** with performance metrics
- **Connection Pooling** for Redis backend
- **Complex Queries** with pagination support

### Security & Stability (v2.1.0)
- **Path Traversal Protection** - Prevents directory escape attacks in filesystem backend
- **SQL Injection Prevention** - Sanitized LIKE patterns in metadata queries
- **Input Validation** - Comprehensive validation on all public API methods
- **Race Condition Fixes** - Atomic buffer operations with proper locking
- **Memory Leak Prevention** - Automatic cleanup of unused key locks
- **Redis SCAN** - Uses SCAN instead of KEYS for production-safe key iteration
- **Abstract Storage Interface** - Consistent API across all storage backends

### Architecture Improvements (v2.2.0)
- **Backend Capabilities System** - Backends declare their capabilities (TTL, transactions, metadata)
- **Unified Write Strategies** - Consistent behavior across all backends
- **Automatic Strategy Selection** - KeyValueStore adapts based on backend capabilities
- **Simplified Codebase** - Removed backend-specific conditionals throughout
- **Extensibility** - Easy to add new backends with custom capabilities

## Installation

```bash
# Basic installation
pip install nadb

# Installation with Redis support
pip install nadb[redis]
```

The basic installation includes only the filesystem backend. If you want to use the Redis backend, you need to install the package with Redis support as shown above.

## 🚀 Quick Start

### Basic Usage

```python
from nadb import KeyValueStore, KeyValueSync

# Setup
kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

# Create store with all advanced features enabled
kv_store = KeyValueStore(
    data_folder_path="./data",
    db="my_app",
    buffer_size_mb=1,
    namespace="production",
    sync=kv_sync,
    compression_enabled=True,
    storage_backend="fs",
    enable_transactions=True,    # 🔄 Enable ACID transactions
    enable_backup=True,          # 💾 Enable backup & recovery
    enable_indexing=True,        # ⚡ Enable intelligent indexing
    cache_size=10000            # 🚀 Cache up to 10K queries
)

# Basic operations
kv_store.set("user:123", b"Alice Johnson", tags=["user", "premium"])
user_data = kv_store.get("user:123")

# Advanced querying with pagination
results = kv_store.query_by_tags_advanced(
    tags=["user", "premium"], 
    operator="AND", 
    page=1, 
    page_size=50
)
print(f"Found {results['total_count']} premium users")

# Cleanup
kv_sync.sync_exit()
```

### 🔄 Transactions

```python
# Atomic operations with automatic rollback
with kv_store.transaction() as tx:
    tx.set("order:1", b"Order data", ["order", "pending"])
    tx.set("inventory:item1", b"Updated count", ["inventory"])
    # Both operations succeed or both fail
```

### 💾 Backup & Recovery

```python
# Create backups
full_backup = kv_store.create_backup("backup_2024_01", compression=True)
incremental = kv_store.create_incremental_backup(full_backup.backup_id)

# Restore from backup
kv_store.restore_backup("backup_2024_01", verify_integrity=True)
```

### ⚡ Advanced Indexing

```python
# Complex queries with caching
conditions = [
    {"field": "tags", "operator": "or", "values": ["premium", "enterprise"]},
    {"field": "tags", "operator": "and", "value": ["active"]}
]
results = kv_store.complex_query(conditions, page=1, page_size=100)
print(f"Query executed in {results['execution_time_ms']:.2f}ms")
```

## 📚 Advanced Features

### 🔄 ACID Transactions
Ensure data consistency with atomic operations:

```python
# All operations succeed or all fail
with kv_store.transaction() as tx:
    tx.set("account:1", b"balance:100", ["account"])
    tx.set("account:2", b"balance:200", ["account"])
    tx.batch_set([
        ("log:1", b"transfer initiated", ["log"]),
        ("log:2", b"transfer completed", ["log"])
    ])
```

### 💾 Backup & Recovery
Enterprise-grade data protection:

```python
# Full backup with compression
backup = kv_store.create_backup("daily_backup", compression=True)

# Incremental backup (only changes)
incremental = kv_store.create_incremental_backup(backup.backup_id)

# Verify and restore
if kv_store.verify_backup(backup.backup_id):
    kv_store.restore_backup(backup.backup_id, clear_existing=True)
```

### ⚡ Intelligent Indexing & Caching
Lightning-fast queries with automatic optimization:

```python
# Advanced queries with pagination
result = kv_store.query_by_tags_advanced(
    tags=["user", "premium"], 
    operator="AND",
    page=1, 
    page_size=50
)

# Complex multi-condition queries
conditions = [
    {"field": "tags", "operator": "or", "values": ["premium", "enterprise"]},
    {"field": "tags", "operator": "and", "value": ["active"]}
]
result = kv_store.complex_query(conditions)

# Cache statistics
stats = kv_store.get_stats()
print(f"Cache hit rate: {stats['cache_stats']['query_cache']['hit_rate']:.2%}")
```

### 📊 Structured Logging
Comprehensive observability with JSON logs:

```python
from logging_config import LoggingConfig

# Get component-specific loggers
logger = LoggingConfig.get_logger('application')
perf_logger = LoggingConfig.get_performance_logger('application')

# Structured logging with metrics
logger.info("User operation", extra={
    'user_id': 'user:123',
    'operation': 'login',
    'ip_address': '192.168.1.100'
})

# Performance tracking
perf_logger.log_metric("active_users", 1250)
```

### 🔗 Connection Pooling (Redis)
Optimized Redis connections for high concurrency:

```python
# Redis backend with connection pooling
kv_store = KeyValueStore(
    storage_backend="redis",
    # Connection pool automatically configured
    # Supports high-concurrency workloads
)
```

### 🏷️ Tag System & Binary Storage
Flexible data organization:

```python
# Store any binary data with tags
with open("document.pdf", "rb") as f:
    kv_store.set("doc:contract", f.read(), tags=["document", "legal", "2024"])

# Query by tags
legal_docs = kv_store.query_by_tags(["legal", "2024"])
```

### ⏰ TTL (Time To Live)
Automatic data expiration:

```python
# Session data that expires in 1 hour
kv_store.set_with_ttl("session:abc123", session_data, 3600, tags=["session"])
```

### 🗜️ Compression & Storage Backends
Efficient storage with multiple backends:

```python
# Filesystem backend (default)
kv_store = KeyValueStore(storage_backend="fs", compression_enabled=True)

# Redis backend for distributed storage
kv_store = KeyValueStore(storage_backend="redis")
```

### 📈 Performance Monitoring
Built-in metrics and statistics:

```python
stats = kv_store.get_stats()
print(f"Total keys: {stats['count']}")
print(f"Cache hit rate: {stats['cache_stats']['query_cache']['hit_rate']:.2%}")
print(f"Active transactions: {stats['active_transactions']}")
print(f"Average query time: {stats['query_stats']['tags_and']['avg_time_ms']:.2f}ms")
```

## Security

NADB v2.1.0 includes several security enhancements:

### Input Validation
All public API methods validate inputs:
```python
# These will raise ValueError
kv_store.set("", b"data")  # Empty key
kv_store.set(None, b"data")  # None key
kv_store.get("")  # Empty key

# These will raise TypeError
kv_store.set("key", "not bytes")  # Value must be bytes
kv_store.set("key", b"data", tags="not-a-list")  # Tags must be list
```

### Path Traversal Protection
The filesystem backend prevents directory escape attacks:
```python
# This will raise ValueError - path traversal attempt
storage.get_full_path("../../../etc/passwd")
```

### SQL Injection Prevention
LIKE patterns are automatically sanitized:
```python
# Safe - special characters are escaped
results = metadata.query_metadata({"key": "test%_pattern"})
```

### Production-Safe Redis Operations
Uses SCAN instead of KEYS command to avoid blocking Redis in production:
```python
# Internally uses SCAN with cursor for large datasets
results = kv_store.query_by_tags(["tag1", "tag2"])
```

## Architecture (v2.2.0)

### Backend Capabilities System

NADB v2.2.0 introduces a powerful capabilities-based architecture that makes backends self-describing and allows KeyValueStore to adapt automatically:

```python
from storage_backends import BackendCapabilities

# Each backend declares its capabilities
class FileSystemStorage(StorageBackend):
    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=True,      # Benefits from in-memory buffering
            supports_native_ttl=False,     # No native TTL support
            supports_metadata=False,       # Uses external SQLite
            write_strategy="buffered",     # Prefers batched writes
            is_distributed=False,          # Local storage
            supports_native_queries=False  # Limited query support
        )

class RedisStorage(StorageBackend):
    def get_capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_buffering=False,      # Redis is fast, no buffering needed
            supports_native_ttl=True,      # Native EXPIRE command
            supports_metadata=True,        # Stores metadata in hashes
            write_strategy="immediate",    # Write directly
            is_distributed=True,           # Networked storage
            supports_native_queries=False  # Limited (SCAN-based)
        )
```

### Automatic Behavior Adaptation

KeyValueStore automatically adapts based on backend capabilities:

```python
# Filesystem backend - uses buffering
kv_fs = KeyValueStore(storage_backend="fs", ...)
# kv_fs.use_buffering == True
# kv_fs.set() writes to buffer, flushes periodically

# Redis backend - immediate writes
kv_redis = KeyValueStore(storage_backend="redis", ...)
# kv_redis.use_buffering == False
# kv_redis.set() writes directly to Redis
```

### Benefits

- **Consistent API**: Same code works with all backends
- **Optimal Performance**: Each backend uses best strategy
- **Easy Extension**: Add new backends by implementing capabilities
- **No Conditionals**: Clean code without `if backend == "redis"` checks

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
