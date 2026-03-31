# Chapter 12: Advanced Features - Structured Logging

Observability is crucial for production systems. NADB's structured logging system provides comprehensive insights into system behavior, performance metrics, and operational health through JSON-formatted logs and specialized performance tracking.

## What is Structured Logging?

**Structured Logging** formats log messages as structured data (JSON) rather than plain text, making logs machine-readable and easily searchable. This enables powerful log analysis, monitoring, and alerting.

NADB's logging system provides:
- **JSON Format**: Machine-readable structured logs
- **Component-Specific Loggers**: Separate loggers for different subsystems
- **Performance Tracking**: Built-in operation timing and metrics
- **Configurable Levels**: Fine-grained control over log verbosity
- **Automatic Rotation**: Prevents log files from growing too large

## Setting Up Structured Logging

NADB automatically initializes structured logging, but you can customize the configuration:

```python
from nadb import KeyValueStore, KeyValueSync
from logging_config import LoggingConfig

# Custom logging configuration
custom_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'structured': {
            '()': 'logging_config.StructuredFormatter',
        },
        'simple': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': 'INFO'
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': './logs/nadb.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'structured',
            'level': 'DEBUG'
        }
    },
    'loggers': {
        'nadb': {
            'level': 'INFO',
            'handlers': ['console', 'file'],
            'propagate': False
        },
        'nadb.storage': {
            'level': 'DEBUG',
            'handlers': ['file'],
            'propagate': False
        }
    }
}

# Setup with custom configuration
LoggingConfig.setup_logging(custom_config, log_dir="./logs")

# Create store (logging is automatically configured)
kv_sync = KeyValueSync(flush_interval_seconds=5)
kv_sync.start()

kv_store = KeyValueStore(
    data_folder_path="./data",
    db="logging_demo",
    buffer_size_mb=1,
    namespace="structured_logs",
    sync=kv_sync
)
```

## Log Components and Levels

### Component-Specific Loggers

NADB uses specialized loggers for different components:

```python
# Get component-specific loggers
storage_logger = LoggingConfig.get_logger('storage')
metadata_logger = LoggingConfig.get_logger('metadata')
sync_logger = LoggingConfig.get_logger('sync')
transaction_logger = LoggingConfig.get_logger('transaction')
backup_logger = LoggingConfig.get_logger('backup')
index_logger = LoggingConfig.get_logger('index')

# Log component-specific messages
storage_logger.info("Storage operation completed", extra={
    'operation': 'write',
    'key': 'user:123',
    'size_bytes': 1024
})

metadata_logger.debug("Metadata updated", extra={
    'key': 'user:123',
    'tags': ['user', 'active'],
    'ttl': 3600
})
```

### Performance Loggers

Performance loggers automatically track operation timing:

```python
# Get performance loggers
storage_perf = LoggingConfig.get_performance_logger('storage')
metadata_perf = LoggingConfig.get_performance_logger('metadata')

# Track an operation
operation_id = "write_user_123"
storage_perf.start_operation(operation_id, "write", key="user:123", size=1024)

# ... perform the operation ...

storage_perf.end_operation(operation_id, success=True, bytes_written=1024)
```

## Structured Log Format

### JSON Log Structure

NADB logs are formatted as JSON with consistent fields:

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "logger": "nadb.storage",
  "message": "Key stored successfully",
  "module": "nakv",
  "function": "set",
  "line": 123,
  "thread_id": 140234567890,
  "operation": "set",
  "key": "user:123",
  "data_size": 1024,
  "duration_ms": 15.5,
  "success": true
}
```

### Performance Log Example

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "logger": "nadb.performance.storage",
  "message": "Operation set completed",
  "operation": "set",
  "duration_ms": 15.5,
  "success": true,
  "key": "user:123",
  "data_size": 1024,
  "thread_id": 140234567890
}
```

## Observing System Behavior

### Basic Operations Logging

```python
# Operations are automatically logged with performance metrics
kv_store.set("user:123", b"Alice Johnson", ["user", "active"])
kv_store.set("user:124", b"Bob Smith", ["user", "inactive"])

# Get operations will also be logged
user_data = kv_store.get("user:123")

# Delete operations too
kv_store.delete("user:124")

# Check the log file to see structured entries for each operation
```

### Transaction Logging

```python
# Transaction operations are logged with transaction context
with kv_store.transaction() as tx:
    tx.set("order:1", b"Order data", ["order", "pending"])
    tx.set("order:2", b"Order data 2", ["order", "pending"])
    # Transaction commit/rollback is automatically logged

# Example transaction log entry:
# {
#   "timestamp": "2024-01-15T10:30:45.123Z",
#   "level": "INFO",
#   "logger": "nadb.transaction",
#   "message": "Transaction committed successfully",
#   "transaction_id": "tx_abc123",
#   "operation_count": 2,
#   "duration_ms": 25.3
# }
```

### Backup Operations Logging

```python
# Backup operations include detailed progress logging
backup_meta = kv_store.create_backup("demo_backup", compression=True)

# Example backup log entries:
# {
#   "timestamp": "2024-01-15T10:30:45.123Z",
#   "level": "INFO", 
#   "logger": "nadb.backup",
#   "message": "Starting full backup demo_backup with 150 keys",
#   "backup_id": "demo_backup",
#   "backup_type": "full",
#   "key_count": 150
# }
# 
# {
#   "timestamp": "2024-01-15T10:30:47.456Z",
#   "level": "INFO",
#   "logger": "nadb.performance.backup", 
#   "message": "Operation full_backup completed",
#   "backup_id": "demo_backup",
#   "duration_ms": 2333.1,
#   "file_count": 150,
#   "total_size": 1048576,
#   "success": true
# }
```

## Custom Logging

### Adding Custom Metrics

```python
# Get a performance logger for custom operations
custom_perf = LoggingConfig.get_performance_logger('custom')

def complex_data_processing(data):
    """Example function with custom performance logging."""
    op_id = f"process_{int(time.time() * 1000)}"
    
    custom_perf.start_operation(op_id, "data_processing", 
                               input_size=len(data),
                               algorithm="custom_v1")
    
    try:
        # Simulate processing
        import time
        time.sleep(0.1)
        
        result = data.upper()  # Simple processing
        
        custom_perf.end_operation(op_id, success=True,
                                 output_size=len(result),
                                 records_processed=1)
        
        return result
        
    except Exception as e:
        custom_perf.end_operation(op_id, success=False, error=str(e))
        raise

# Use the function
result = complex_data_processing(b"test data")
```

### Logging Custom Metrics

```python
# Log custom metrics
app_logger = LoggingConfig.get_logger('application')
perf_logger = LoggingConfig.get_performance_logger('application')

# Log application events
app_logger.info("User login successful", extra={
    'user_id': 'user:123',
    'login_method': 'oauth',
    'ip_address': '192.168.1.100'
})

# Log custom metrics
perf_logger.log_metric("active_users", 1250, region="us-east-1")
perf_logger.log_metric("cache_hit_rate", 0.85, cache_type="query_cache")
perf_logger.log_metric("memory_usage_mb", 512.5, component="index_manager")
```

## Log Analysis and Monitoring

### Parsing Structured Logs

```python
import json

def analyze_performance_logs(log_file_path):
    """Analyze performance from structured logs."""
    operations = {}
    
    with open(log_file_path, 'r') as f:
        for line in f:
            try:
                log_entry = json.loads(line.strip())
                
                # Focus on performance logs
                if 'duration_ms' in log_entry and 'operation' in log_entry:
                    op_type = log_entry['operation']
                    duration = log_entry['duration_ms']
                    
                    if op_type not in operations:
                        operations[op_type] = []
                    
                    operations[op_type].append(duration)
                    
            except json.JSONDecodeError:
                continue
    
    # Calculate statistics
    for op_type, durations in operations.items():
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)
        
        print(f"{op_type}:")
        print(f"  Count: {len(durations)}")
        print(f"  Average: {avg_duration:.2f}ms")
        print(f"  Min: {min_duration:.2f}ms")
        print(f"  Max: {max_duration:.2f}ms")

# Run analysis
# analyze_performance_logs("./logs/nadb.log")
```

### Error Analysis

```python
def analyze_errors(log_file_path):
    """Analyze errors from structured logs."""
    errors = {}
    
    with open(log_file_path, 'r') as f:
        for line in f:
            try:
                log_entry = json.loads(line.strip())
                
                if log_entry.get('level') == 'ERROR':
                    error_type = log_entry.get('logger', 'unknown')
                    message = log_entry.get('message', 'No message')
                    
                    if error_type not in errors:
                        errors[error_type] = []
                    
                    errors[error_type].append({
                        'timestamp': log_entry.get('timestamp'),
                        'message': message,
                        'function': log_entry.get('function'),
                        'line': log_entry.get('line')
                    })
                    
            except json.JSONDecodeError:
                continue
    
    # Report errors
    for error_type, error_list in errors.items():
        print(f"\n{error_type} errors: {len(error_list)}")
        for error in error_list[-5:]:  # Show last 5 errors
            print(f"  {error['timestamp']}: {error['message']}")

# Run error analysis
# analyze_errors("./logs/nadb.log")
```

## Integration with Monitoring Systems

### Prometheus Metrics Export

```python
def export_metrics_to_prometheus():
    """Export NADB metrics in Prometheus format."""
    stats = kv_store.get_stats()
    
    metrics = []
    
    # Basic metrics
    metrics.append(f'nadb_total_keys{{db="{stats["database"]}",namespace="{stats["namespace"]}"}} {stats["count"]}')
    metrics.append(f'nadb_uptime_seconds{{db="{stats["database"]}"}} {stats["performance"]["uptime_seconds"]}')
    
    # Performance metrics
    if 'operations' in stats['performance']:
        for op_name, op_stats in stats['performance']['operations'].items():
            metrics.append(f'nadb_operation_count{{operation="{op_name}"}} {op_stats["count"]}')
            metrics.append(f'nadb_operation_avg_duration_ms{{operation="{op_name}"}} {op_stats["avg_ms"]}')
    
    # Cache metrics
    if 'cache_stats' in stats:
        for cache_name, cache_stats in stats['cache_stats'].items():
            metrics.append(f'nadb_cache_hit_rate{{cache="{cache_name}"}} {cache_stats["hit_rate"]}')
            metrics.append(f'nadb_cache_size{{cache="{cache_name}"}} {cache_stats["size"]}')
    
    return '\n'.join(metrics)

# Export metrics
prometheus_metrics = export_metrics_to_prometheus()
print(prometheus_metrics)
```

### ELK Stack Integration

```python
def format_for_elasticsearch():
    """Format logs for Elasticsearch ingestion."""
    # NADB's JSON logs are already compatible with Elasticsearch
    # You can use Filebeat or Logstash to ship logs
    
    # Example Filebeat configuration:
    filebeat_config = """
    filebeat.inputs:
    - type: log
      enabled: true
      paths:
        - /path/to/nadb.log
      json.keys_under_root: true
      json.add_error_key: true
      fields:
        service: nadb
        environment: production
    
    output.elasticsearch:
      hosts: ["localhost:9200"]
      index: "nadb-logs-%{+yyyy.MM.dd}"
    """
    
    return filebeat_config
```

## Best Practices

### 1. Configure Appropriate Log Levels

```python
# Production configuration
production_config = {
    'loggers': {
        'nadb': {'level': 'INFO'},           # General info
        'nadb.storage': {'level': 'WARNING'}, # Only warnings/errors
        'nadb.performance': {'level': 'INFO'}, # Performance metrics
        'nadb.transaction': {'level': 'INFO'}, # Transaction events
        'nadb.backup': {'level': 'INFO'},      # Backup operations
    }
}

# Development configuration  
development_config = {
    'loggers': {
        'nadb': {'level': 'DEBUG'},          # Detailed debugging
        'nadb.storage': {'level': 'DEBUG'},   # Storage operations
        'nadb.metadata': {'level': 'DEBUG'},  # Metadata operations
    }
}
```

### 2. Monitor Key Metrics

```python
def health_check_from_logs():
    """Perform health checks based on log analysis."""
    stats = kv_store.get_stats()
    
    alerts = []
    
    # Check error rates
    if 'performance' in stats and 'operations' in stats['performance']:
        for op_name, op_stats in stats['performance']['operations'].items():
            if op_stats['avg_ms'] > 1000:  # Operations taking > 1 second
                alerts.append(f"Slow {op_name} operations: {op_stats['avg_ms']:.2f}ms average")
    
    # Check cache performance
    if 'cache_stats' in stats:
        for cache_name, cache_stats in stats['cache_stats'].items():
            if cache_stats['hit_rate'] < 0.5:  # Less than 50% hit rate
                alerts.append(f"Low cache hit rate for {cache_name}: {cache_stats['hit_rate']:.2%}")
    
    # Check active transactions
    if stats.get('active_transactions', 0) > 10:
        alerts.append(f"High number of active transactions: {stats['active_transactions']}")
    
    return alerts

# Run health check
alerts = health_check_from_logs()
for alert in alerts:
    print(f"⚠️  {alert}")
```

### 3. Log Retention and Rotation

```python
# Configure log rotation
rotation_config = {
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': './logs/nadb.log',
            'maxBytes': 50 * 1024 * 1024,  # 50MB per file
            'backupCount': 10,              # Keep 10 backup files
            'formatter': 'structured'
        },
        'timed_file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': './logs/nadb-daily.log',
            'when': 'midnight',             # Rotate daily
            'interval': 1,
            'backupCount': 30,              # Keep 30 days
            'formatter': 'structured'
        }
    }
}
```

## Troubleshooting with Logs

### Common Log Patterns

```python
# Performance degradation
# Look for: increasing duration_ms values
# Example: {"operation": "set", "duration_ms": 150.5, "success": true}

# Memory issues  
# Look for: cache evictions, index rebuilds
# Example: {"message": "Cache eviction due to memory pressure"}

# Connection issues (Redis)
# Look for: connection errors, reconnection attempts
# Example: {"level": "ERROR", "message": "Redis connection failed"}

# Transaction conflicts
# Look for: rollback events, long-running transactions
# Example: {"message": "Transaction rolled back", "reason": "timeout"}
```

### Debug Mode

```python
# Enable debug logging for troubleshooting
debug_config = LoggingConfig.DEFAULT_CONFIG.copy()
debug_config['loggers']['nadb']['level'] = 'DEBUG'

LoggingConfig.setup_logging(debug_config)

# Now all operations will be logged in detail
kv_store.set("debug_key", b"debug_value", ["debug"])
```

## Conclusion

NADB's structured logging system provides:
- **Comprehensive Observability**: Detailed insights into all system operations
- **Performance Monitoring**: Built-in timing and metrics collection
- **Machine-Readable Format**: JSON logs for easy analysis and monitoring
- **Component Isolation**: Separate loggers for different subsystems
- **Production Ready**: Configurable levels, rotation, and integration support

Structured logging is essential for:
- **Debugging**: Detailed operation traces for troubleshooting
- **Performance Optimization**: Identifying bottlenecks and slow operations
- **Monitoring**: Real-time system health and alerting
- **Compliance**: Audit trails and operational records

Combined with NADB's other advanced features, structured logging provides the observability needed for production deployments.

---

This concludes our comprehensive tour of NADB's advanced features. You now have the knowledge to leverage transactions, backup & recovery, indexing & caching, and structured logging to build robust, high-performance applications with NADB.