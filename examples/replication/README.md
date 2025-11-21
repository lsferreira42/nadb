# NADB Network Replication Examples

This directory contains examples demonstrating NADB's network replication capabilities.

## Overview

NADB supports network replication with a primary-secondary (master-slave) architecture:

- **Primary Node**: Accepts writes and broadcasts operations to all connected replicas
- **Secondary Nodes**: Read-only replicas that receive and apply operations from the primary

## Quick Start

### 1. Start Primary Node

In one terminal:

```bash
cd examples/replication
python primary_node.py
```

The primary will:
- Start a replication server on port 9000
- Accept write operations
- Broadcast changes to all connected replicas
- Maintain an operation log for catch-up

### 2. Start Secondary Node(s)

In another terminal (you can start multiple secondaries):

```bash
cd examples/replication
python secondary_node.py
```

The secondary will:
- Connect to the primary at localhost:9000
- Receive and apply replicated operations
- Operate in read-only mode
- Automatically reconnect on disconnection

### 3. Custom Primary Host/Port

You can configure the secondary to connect to a different primary:

```bash
PRIMARY_HOST=192.168.1.10 PRIMARY_PORT=9000 python secondary_node.py
```

## Architecture

```
┌─────────────────────┐
│   Primary Node      │
│  (localhost:9000)   │
│                     │
│  - Accepts writes   │
│  - Broadcasts ops   │
└──────────┬──────────┘
           │
    ┌──────┴───────┬─────────────┐
    │              │             │
    ▼              ▼             ▼
┌────────┐    ┌────────┐    ┌────────┐
│Secondary│    │Secondary│    │Secondary│
│   #1    │    │   #2    │    │   #3    │
│         │    │         │    │         │
│Read-Only│    │Read-Only│    │Read-Only│
└─────────┘    └─────────┘    └─────────┘
```

## Features Demonstrated

### Primary Node Features
- Operation broadcasting
- Replica management
- Automatic catch-up for new replicas
- Heartbeat monitoring
- Operation log maintenance

### Secondary Node Features
- Automatic connection/reconnection
- Read-only enforcement
- Operation reception and application
- Statistics and monitoring

## Network Protocol

Operations are serialized as JSON over TCP with:
- Length prefix (4 bytes, big-endian)
- JSON payload with operation data
- SHA256 checksum for integrity
- Sequence numbers for ordering

## Configuration Options

### Primary Configuration

```python
replication_config = {
    'mode': 'primary',
    'listen_host': '0.0.0.0',       # Bind address
    'listen_port': 9000,             # Listening port
    'heartbeat_interval': 5,         # Heartbeat frequency (seconds)
    'max_operation_log': 10000,      # Operations to keep for catch-up
    'broadcast_async': True          # Non-blocking broadcast
}
```

### Secondary Configuration

```python
replication_config = {
    'mode': 'secondary',
    'primary_host': 'localhost',     # Primary host
    'primary_port': 9000             # Primary port
}
```

## Monitoring

### Primary Statistics

```python
stats = network_backend.get_replication_stats()

print(f"Mode: {stats['mode']}")
print(f"Sequence: {stats['sequence_number']}")
print(f"Replicas: {stats['replica_count']}")

for replica in stats['replicas']:
    print(f"  - {replica['replica_id']}: {replica['operations_sent']} ops sent")
```

### Secondary Statistics

```python
stats = network_backend.get_replication_stats()

if 'primary' in stats:
    print(f"Connected: {stats['primary']['connected']}")
    print(f"Operations received: {stats['primary']['operations_received']}")
    print(f"Last sequence: {stats['primary']['last_applied_sequence']}")
```

## Testing Scenarios

### 1. Normal Operation
1. Start primary
2. Start secondary
3. Observe synchronization

### 2. Late Join
1. Start primary and write data
2. Start secondary after data is written
3. Observe catch-up mechanism

### 3. Network Interruption
1. Start both nodes
2. Kill secondary (Ctrl+C)
3. Write more data to primary
4. Restart secondary
5. Observe catch-up

### 4. Multiple Replicas
1. Start primary
2. Start multiple secondaries
3. Write data to primary
4. Observe all secondaries receive updates

## Limitations

- **Eventual Consistency**: Secondary nodes may lag behind primary
- **No Automatic Failover**: Manual intervention needed if primary fails
- **Single Primary**: Only one writable node at a time
- **No Conflict Resolution**: Designed for master-slave, not multi-master

## Production Considerations

For production use, consider:

1. **Monitoring**: Track replication lag and connection status
2. **Alerting**: Alert on disconnections or high lag
3. **Networking**: Use reliable network infrastructure
4. **Firewall**: Open port 9000 (or configured port) between nodes
5. **Security**: Consider adding authentication/encryption (not included in examples)
6. **Resources**: Each replica maintains operation log in memory
7. **Persistence**: Operation log is in-memory only (lost on restart)

## Next Steps

See the main documentation in `docs/` for:
- Integration with KeyValueStore
- Advanced configuration options
- Performance tuning
- Security best practices
