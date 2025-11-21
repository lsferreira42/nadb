"""
Example: Primary Node with Network Replication

This example shows how to set up a NADB primary node that:
- Accepts write operations
- Broadcasts changes to all connected replicas
- Maintains operation log for catch-up

Usage:
    python primary_node.py
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from nakv import KeyValueStore, KeyValueSync
from storage_backends import StorageFactory
from storage_backends.network_sync import NetworkSyncBackend
from storage_backends.fs import FileSystemStorage


def main():
    print("=" * 60)
    print("NADB Primary Node - Network Replication Example")
    print("=" * 60)
    print()

    # Create sync engine
    print("Creating KeyValueSync...")
    kv_sync = KeyValueSync(flush_interval_seconds=5)
    kv_sync.start()

    # Create base backend (filesystem)
    print("Creating base storage backend (filesystem)...")
    base_backend = FileSystemStorage(base_path="./data_primary")

    # Configure replication (primary mode)
    replication_config = {
        'mode': 'primary',
        'listen_host': '0.0.0.0',  # Listen on all interfaces
        'listen_port': 9000,
        'heartbeat_interval': 5,  # Send heartbeat every 5 seconds
        'max_operation_log': 10000,  # Keep last 10K operations for catch-up
        'broadcast_async': True  # Non-blocking broadcast
    }

    # Create network sync backend
    print(f"Creating network sync backend (primary) on port {replication_config['listen_port']}...")
    network_backend = NetworkSyncBackend(
        base_backend=base_backend,
        mode='primary',
        config=replication_config
    )

    # Set the backend context
    network_backend.set_context(db="example_db", namespace="default")

    print()
    print("Primary node started successfully!")
    print(f"  - Listening for replicas on 0.0.0.0:9000")
    print(f"  - Database: example_db")
    print(f"  - Namespace: default")
    print()

    # Perform some operations
    print("Performing write operations...")
    print()

    # Write some data
    operations = [
        ("user:1", b"Alice", ["user", "active"]),
        ("user:2", b"Bob", ["user", "active"]),
        ("user:3", b"Charlie", ["user", "inactive"]),
        ("product:1", b"Laptop", ["product", "electronics"]),
        ("product:2", b"Mouse", ["product", "electronics", "accessory"]),
        ("order:1", b"Order data 1", ["order", "pending"]),
        ("order:2", b"Order data 2", ["order", "shipped"]),
    ]

    for i, (key, value, tags) in enumerate(operations, 1):
        # Build path
        from hashlib import blake2b
        h = blake2b(digest_size=16)
        h.update(f"example_db:default:{key}".encode('utf-8'))
        key_hash = h.hexdigest()
        path = f"example_db/{key_hash[0:2]}/{key_hash[2:4]}/{key_hash}"

        # Write with replication
        network_backend.write_with_replication(
            relative_path=path,
            data=value,
            key=key,
            tags=tags
        )

        print(f"  [{i}/{len(operations)}] Wrote: {key} = {value.decode('utf-8')} (tags: {tags})")
        time.sleep(0.5)  # Small delay to simulate real workload

    print()
    print("All operations completed!")
    print()

    # Show replication stats
    print("Replication Statistics:")
    print("-" * 60)
    stats = network_backend.get_replication_stats()

    print(f"  Mode: {stats['mode']}")
    print(f"  Sequence Number: {stats['sequence_number']}")
    print(f"  Operation Log Size: {stats['operation_log_size']}")
    print(f"  Connected Replicas: {stats.get('replica_count', 0)}")
    print()

    if stats.get('replicas'):
        print("  Replica Details:")
        for replica in stats['replicas']:
            print(f"    - {replica['replica_id']}:")
            print(f"        Address: {replica['address']}")
            print(f"        Connected: {replica['connected']}")
            print(f"        Operations Sent: {replica['operations_sent']}")
            print(f"        Bytes Sent: {replica['bytes_sent']}")
            print(f"        Lag: {replica['lag_seconds']:.1f}s")
        print()

    # Keep running to accept replicas
    print("Primary node is running. Press Ctrl+C to stop.")
    print("Secondary replicas can now connect to receive updates.")
    print()

    try:
        while True:
            time.sleep(5)

            # Show live stats every 5 seconds
            stats = network_backend.get_replication_stats()
            replica_count = stats.get('replica_count', 0)

            print(f"[{time.strftime('%H:%M:%S')}] Active replicas: {replica_count}, "
                  f"Operations in log: {stats['operation_log_size']}")

    except KeyboardInterrupt:
        print()
        print("Shutting down primary node...")

    finally:
        # Cleanup
        network_backend.close_connections()
        kv_sync.sync_exit()
        print("Primary node stopped.")


if __name__ == '__main__':
    main()
