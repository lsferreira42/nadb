"""
Example: Secondary (Read Replica) Node with Network Replication

This example shows how to set up a NADB secondary node that:
- Connects to a primary node
- Receives and applies replicated operations
- Operates in read-only mode
- Automatically reconnects on failure

Usage:
    # First start primary_node.py, then run:
    python secondary_node.py
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from storage_backends.network_sync import NetworkSyncBackend
from storage_backends.fs import FileSystemStorage
from replication.exceptions import ReadOnlyError


def main():
    print("=" * 60)
    print("NADB Secondary Node - Network Replication Example")
    print("=" * 60)
    print()

    # Create base backend (filesystem - separate data directory)
    print("Creating base storage backend (filesystem)...")
    base_backend = FileSystemStorage(base_path="./data_secondary")

    # Configure replication (secondary mode)
    primary_host = os.environ.get('PRIMARY_HOST', 'localhost')
    primary_port = int(os.environ.get('PRIMARY_PORT', '9000'))

    replication_config = {
        'mode': 'secondary',
        'primary_host': primary_host,
        'primary_port': primary_port
    }

    # Create network sync backend
    print(f"Creating network sync backend (secondary)...")
    print(f"  Connecting to primary at {primary_host}:{primary_port}...")
    network_backend = NetworkSyncBackend(
        base_backend=base_backend,
        mode='secondary',
        config=replication_config
    )

    # Set the backend context
    network_backend.set_context(db="example_db", namespace="default")

    print()
    print("Secondary node started successfully!")
    print(f"  - Mode: Read-Only Replica")
    print(f"  - Primary: {primary_host}:{primary_port}")
    print(f"  - Database: example_db")
    print(f"  - Namespace: default")
    print()

    # Test read-only enforcement
    print("Testing read-only enforcement...")
    try:
        network_backend.write_data("test/path", b"test")
        print("  ERROR: Write should have been rejected!")
    except ReadOnlyError:
        print("  ✓ Write correctly rejected (read-only mode)")
    print()

    # Wait for initial sync
    print("Waiting for initial synchronization from primary...")
    time.sleep(3)

    # Monitor replication
    print()
    print("Secondary node is running and receiving updates from primary.")
    print("Press Ctrl+C to stop.")
    print()

    last_sequence = 0
    last_operations = 0

    try:
        while True:
            time.sleep(5)

            # Show live stats
            stats = network_backend.get_replication_stats()

            if 'primary' in stats:
                primary_stats = stats['primary']
                connected = primary_stats.get('connected', False)
                ops_received = primary_stats.get('operations_received', 0)
                last_applied = stats.get('primary', {}).get('last_applied_sequence', 0)

                # Calculate ops per second
                ops_delta = ops_received - last_operations
                ops_per_sec = ops_delta / 5.0

                status = "✓ CONNECTED" if connected else "✗ DISCONNECTED"
                print(f"[{time.strftime('%H:%M:%S')}] {status} | "
                      f"Ops received: {ops_received} (+{ops_delta}) | "
                      f"Last sequence: {last_applied} | "
                      f"Rate: {ops_per_sec:.1f} ops/s")

                if not connected:
                    print(f"              Attempting to reconnect to {primary_host}:{primary_port}...")

                last_sequence = last_applied
                last_operations = ops_received

                # Show lag if available
                seconds_since_last_op = primary_stats.get('seconds_since_last_operation', 0)
                if connected and seconds_since_last_op > 10:
                    print(f"              Note: No operations received for {seconds_since_last_op:.0f}s")

            else:
                print(f"[{time.strftime('%H:%M:%S')}] Waiting for primary connection...")

    except KeyboardInterrupt:
        print()
        print("Shutting down secondary node...")

    finally:
        # Cleanup
        network_backend.close_connections()
        print("Secondary node stopped.")


if __name__ == '__main__':
    main()
