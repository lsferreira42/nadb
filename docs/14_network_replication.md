# Network Replication

**Version: 2.3.0+**

NADB supports network-based replication allowing you to synchronize data and metadata across multiple nodes. This enables:

- **High Availability**: Multiple replicas ensure data availability even if one node fails
- **Read Scaling**: Distribute read load across multiple secondary nodes
- **Geographic Distribution**: Place replicas in different locations
- **Disaster Recovery**: Maintain copies of data in separate locations

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Primary-Secondary Model](#primary-secondary-model)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [Operations](#operations)
6. [Monitoring](#monitoring)
7. [Best Practices](#best-practices)
8. [Limitations](#limitations)

---

## Architecture Overview

NADB replication follows a **primary-secondary (master-slave)** architecture:

```
┌───────────────────────┐
│   PRIMARY NODE        │
│   (Accepts writes)    │
│                       │
│ ┌─────────────────┐   │
│ │ Storage Backend │   │
│ │   (fs/redis)    │   │
│ └─────────────────┘   │
│         ↓              │
│ ┌─────────────────┐   │
│ │Replication      │   │
│ │Server (TCP)     │   │
│ └─────────────────┘   │
└──────────┬────────────┘
           │ Operations Stream
    ┌──────┼──────┬─────────┐
    │      │      │         │
    ▼      ▼      ▼         ▼
┌────────┐ ... ┌────────┐
│Secondary│    │Secondary│
│  Node  │    │  Node  │
│(Read   │    │(Read   │
│ Only)  │    │ Only)  │
└────────┘    └────────┘
```

### Key Components

1. **Replication Protocol**: JSON-based protocol for serializing operations
2. **Replication Manager**: Core logic for managing replication state
3. **Replication Server**: TCP server on primary accepting replica connections
4. **Replication Client**: TCP client on secondary connecting to primary
5. **Network Sync Backend**: Storage backend wrapper adding replication

---

## Primary-Secondary Model

### Primary Node

The primary node:
- **Accepts all write operations** (SET, DELETE, TTL updates)
- **Broadcasts operations** to all connected secondary nodes
- **Maintains operation log** for catch-up when replicas reconnect
- **Tracks replica status** via heartbeats

### Secondary Node(s)

Secondary nodes:
- **Receive operations** from primary via TCP stream
- **Apply operations** to local storage backend
- **Read-only**: Reject all write attempts
- **Automatic reconnection** on network failures
- **Catch-up mechanism** for missed operations

---

## Quick Start

### Step 1: Start Primary Node

```python
from storage_backends.network_sync import NetworkSyncBackend
from storage_backends.fs import FileSystemStorage

# Create base storage backend
base_backend = FileSystemStorage(base_path="./data_primary")

# Configure replication (primary mode)
replication_config = {
    'mode': 'primary',
    'listen_host': '0.0.0.0',  # Listen on all interfaces
    'listen_port': 9000,
    'heartbeat_interval': 5,
    'max_operation_log': 10000
}

# Create network sync backend
network_backend = NetworkSyncBackend(
    base_backend=base_backend,
    mode='primary',
    config=replication_config
)

# Set database context
network_backend.set_context(db="mydb", namespace="production")

# Write data (will be replicated)
network_backend.write_with_replication(
    relative_path="path/to/data",
    data=b"my data",
    key="my_key",
    tags=["tag1", "tag2"]
)
```

### Step 2: Start Secondary Node(s)

```python
from storage_backends.network_sync import NetworkSyncBackend
from storage_backends.fs import FileSystemStorage

# Create base storage backend (separate data directory)
base_backend = FileSystemStorage(base_path="./data_secondary")

# Configure replication (secondary mode)
replication_config = {
    'mode': 'secondary',
    'primary_host': 'primary.example.com',
    'primary_port': 9000
}

# Create network sync backend
network_backend = NetworkSyncBackend(
    base_backend=base_backend,
    mode='secondary',
    config=replication_config
)

# Read data (served from local replica)
data = network_backend.read_data("path/to/data")

# Writes will be rejected
try:
    network_backend.write_data("path", b"data")
except ReadOnlyError:
    print("Cannot write to read-only replica!")
```

---

## Configuration

### Primary Configuration

```python
replication_config = {
    # Required
    'mode': 'primary',

    # Network settings
    'listen_host': '0.0.0.0',      # Bind address (0.0.0.0 = all interfaces)
    'listen_port': 9000,           # Port to listen on

    # Performance tuning
    'heartbeat_interval': 5,       # Heartbeat frequency (seconds)
    'max_operation_log': 10000,    # Max operations to keep for catch-up
    'broadcast_async': True        # Non-blocking broadcast (recommended)
}
```

### Secondary Configuration

```python
replication_config = {
    # Required
    'mode': 'secondary',
    'primary_host': '192.168.1.10',  # Primary node address

    # Network settings
    'primary_port': 9000,            # Primary port (default: 9000)
}
```

---

## Operations

### Replicated Operations

The following operations are automatically replicated:

1. **SET**: Key-value writes with tags and TTL
2. **DELETE**: Key deletions
3. **METADATA**: Metadata updates

### Write Operations (Primary Only)

```python
# Simple write
network_backend.write_data(path, data)

# Write with full replication context
network_backend.write_with_replication(
    relative_path=path,
    data=b"value",
    key="user:123",
    tags=["user", "active"],
    ttl=3600  # 1 hour
)

# Delete with replication
network_backend.delete_with_replication(
    relative_path=path,
    key="user:123"
)
```

### Read Operations (Both Modes)

```python
# Reads work on both primary and secondary
data = network_backend.read_data(path)

# Check existence
exists = network_backend.file_exists(path)

# Get file size
size = network_backend.get_file_size(path)
```

---

## Monitoring

### Get Replication Statistics

```python
stats = network_backend.get_replication_stats()

print(f"Mode: {stats['mode']}")
print(f"Sequence: {stats['sequence_number']}")
print(f"Operation Log: {stats['operation_log_size']}")
```

### Primary Statistics

```python
stats = network_backend.get_replication_stats()

# Number of connected replicas
replica_count = stats.get('replica_count', 0)

# Per-replica statistics
for replica in stats.get('replicas', []):
    print(f"Replica: {replica['replica_id']}")
    print(f"  Connected: {replica['connected']}")
    print(f"  Operations Sent: {replica['operations_sent']}")
    print(f"  Bytes Sent: {replica['bytes_sent']}")
    print(f"  Lag: {replica['lag_seconds']:.1f}s")
```

### Secondary Statistics

```python
stats = network_backend.get_replication_stats()

if 'primary' in stats:
    primary = stats['primary']
    print(f"Connected to Primary: {primary['connected']}")
    print(f"Operations Received: {primary['operations_received']}")
    print(f"Last Sequence Applied: {primary['last_applied_sequence']}")
    print(f"Seconds Since Last Op: {primary['seconds_since_last_operation']}")
```

---

## Best Practices

### 1. Network Configuration

- **Firewall Rules**: Ensure port 9000 (or configured port) is open between nodes
- **Network Reliability**: Use reliable network connections between nodes
- **Latency**: Keep replicas on low-latency networks for better performance

### 2. Resource Planning

- **Memory**: Operation log is kept in memory (default: 10,000 operations)
- **Bandwidth**: Consider network bandwidth for high-write workloads
- **CPU**: Serialization/deserialization has CPU overhead

### 3. Monitoring

- **Track Replication Lag**: Monitor `lag_seconds` on replicas
- **Connection Status**: Alert on disconnections
- **Operation Rate**: Monitor operations per second

### 4. Failure Handling

- **Automatic Reconnection**: Secondary nodes automatically reconnect
- **Catch-up Mechanism**: Missed operations are replayed from log
- **Primary Failure**: Manual intervention required (no automatic failover)

### 5. Security

⚠️ **Current Implementation**: No built-in authentication or encryption

For production use, consider:
- Running over VPN or private network
- Using firewall rules to restrict access
- Implementing network-level encryption (IPsec, WireGuard)

### 6. Deployment Patterns

#### Read Scaling

```
1 Primary (writes) + N Secondaries (reads)
```

Distribute read load across multiple replicas.

#### Geographic Distribution

```
Primary (US East) → Secondary (US West)
                  → Secondary (Europe)
```

Place replicas closer to users for lower latency reads.

#### Disaster Recovery

```
Primary (Production DC) → Secondary (Backup DC)
```

Maintain a backup copy in a separate data center.

---

## Limitations

### Current Limitations

1. **Single Primary**: Only one writable node at a time
2. **No Automatic Failover**: Manual intervention needed if primary fails
3. **Eventual Consistency**: Secondaries may lag behind primary
4. **No Conflict Resolution**: Not designed for multi-primary
5. **In-Memory Log**: Operation log is not persisted (lost on restart)
6. **No Authentication**: No built-in authentication or encryption

### When to Use

✅ **Good fit for:**
- Read-heavy workloads
- Geographic distribution
- High availability reads
- Disaster recovery

❌ **Not suitable for:**
- Write-heavy workloads requiring multiple writers
- Strong consistency requirements
- Scenarios requiring automatic failover

---

## Replication Protocol

### Protocol Format

Operations are serialized as JSON over TCP:

```json
{
  "type": "SET",
  "sequence": 123,
  "timestamp": 1234567890.123,
  "data": {
    "key": "user:123",
    "value": "base64_encoded_bytes",
    "db": "mydb",
    "namespace": "production",
    "tags": ["user", "active"],
    "ttl": 3600
  },
  "checksum": "sha256_hex"
}
```

### Protocol Features

- **Length Prefix**: 4-byte length prefix for framing
- **Checksum**: SHA256 checksum for integrity
- **Sequence Numbers**: Monotonic sequence for ordering
- **Timestamps**: Unix timestamps for operation timing
- **Binary Support**: Base64 encoding for binary values

### Operation Types

- `SET`: Write operation
- `DELETE`: Delete operation
- `HEARTBEAT`: Keep-alive message
- `SYNC_REQUEST`: Request catch-up from sequence
- `SYNC_RESPONSE`: Response with operations

---

## Example: Complete Setup

See `examples/replication/` for complete working examples:

- `primary_node.py`: Example primary node setup
- `secondary_node.py`: Example secondary node setup
- `README.md`: Detailed setup instructions

---

## See Also

- [Backend Capabilities System](13_backend_capabilities_system.md)
- [Structured Logging](12_structured_logging.md)
- [Performance Monitoring](index.md)

---

**Next Steps:**
- Review [example code](../examples/replication/)
- Set up test primary and secondary
- Monitor replication statistics
- Plan production deployment
