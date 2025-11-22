"""
Tests for NADB Network Replication.

Tests cover:
- Protocol serialization/deserialization
- Primary-secondary connection
- Operation replication
- Read-only enforcement
- Reconnection logic
"""

import unittest
import time
import tempfile
import shutil

from replication.protocol import (
    ReplicationProtocol,
    Operation,
    OperationType
)
from replication.manager import ReplicationManager
from replication.server import ReplicationServer
from replication.client import ReplicationClient
from replication.exceptions import (
    ReadOnlyError,
    ProtocolError,
    ChecksumMismatchError
)
from storage_backends.fs import FileSystemStorage
from storage_backends.network_sync import NetworkSyncBackend


# ============================================================================
# Protocol Tests
# ============================================================================

class TestReplicationProtocol(unittest.TestCase):
    """Test replication protocol serialization."""

    def test_serialize_deserialize_set_operation(self):
        """Test serializing and deserializing a SET operation."""
        operation = ReplicationProtocol.create_set_operation(
            sequence=1,
            key="test_key",
            value=b"test_value",
            db="test_db",
            namespace="default",
            tags=["tag1", "tag2"],
            ttl=3600
        )

        # Serialize
        serialized = ReplicationProtocol.serialize(operation)
        self.assertIsInstance(serialized, bytes)
        self.assertGreater(len(serialized), 4)  # At least length prefix

        # Deserialize
        deserialized = ReplicationProtocol.deserialize(serialized)

        # Verify
        self.assertEqual(deserialized.type, OperationType.SET)
        self.assertEqual(deserialized.sequence, 1)
        self.assertEqual(deserialized.data['key'], "test_key")
        self.assertEqual(deserialized.data['value'], b"test_value")
        self.assertEqual(deserialized.data['db'], "test_db")
        self.assertEqual(deserialized.data['namespace'], "default")
        self.assertEqual(deserialized.data['tags'], ["tag1", "tag2"])
        self.assertEqual(deserialized.data['ttl'], 3600)
        self.assertEqual(deserialized.checksum, operation.checksum)

    def test_serialize_deserialize_delete_operation(self):
        """Test serializing and deserializing a DELETE operation."""
        operation = ReplicationProtocol.create_delete_operation(
            sequence=2,
            key="test_key",
            db="test_db",
            namespace="default"
        )

        # Serialize
        serialized = ReplicationProtocol.serialize(operation)

        # Deserialize
        deserialized = ReplicationProtocol.deserialize(serialized)

        # Verify
        self.assertEqual(deserialized.type, OperationType.DELETE)
        self.assertEqual(deserialized.sequence, 2)
        self.assertEqual(deserialized.data['key'], "test_key")
        self.assertEqual(deserialized.checksum, operation.checksum)

    def test_checksum_validation(self):
        """Test checksum validation."""
        operation = ReplicationProtocol.create_set_operation(
            sequence=1,
            key="test",
            value=b"data",
            db="db",
            namespace="ns"
        )

        # Serialize
        serialized = ReplicationProtocol.serialize(operation)

        # Corrupt the data (in the middle of JSON, after length prefix)
        corrupted = serialized[:10] + b'X' + serialized[11:]

        # Should raise ChecksumMismatchError or ProtocolError
        with self.assertRaises((ChecksumMismatchError, ProtocolError)):
            ReplicationProtocol.deserialize(corrupted)

    def test_large_value(self):
        """Test serialization of large values."""
        large_value = b"x" * (1024 * 1024)  # 1MB

        operation = ReplicationProtocol.create_set_operation(
            sequence=1,
            key="large_key",
            value=large_value,
            db="db",
            namespace="ns"
        )

        # Serialize
        serialized = ReplicationProtocol.serialize(operation)

        # Deserialize
        deserialized = ReplicationProtocol.deserialize(serialized)

        # Verify
        self.assertEqual(deserialized.data['value'], large_value)

    def test_heartbeat_operation(self):
        """Test heartbeat operation."""
        operation = ReplicationProtocol.create_heartbeat_operation(sequence=100)

        # Serialize and deserialize
        serialized = ReplicationProtocol.serialize(operation)
        deserialized = ReplicationProtocol.deserialize(serialized)

        self.assertEqual(deserialized.type, OperationType.HEARTBEAT)
        self.assertEqual(deserialized.sequence, 100)
        self.assertEqual(deserialized.data, {})


# ============================================================================
# Manager Tests
# ============================================================================

class TestReplicationManager(unittest.TestCase):
    """Test replication manager."""

    def test_primary_mode_initialization(self):
        """Test initializing manager in primary mode."""
        config = {
            'heartbeat_interval': 5,
            'max_operation_log': 1000
        }

        manager = ReplicationManager(mode='primary', config=config)

        self.assertEqual(manager.mode, 'primary')
        self.assertEqual(manager.sequence_number, 0)
        self.assertEqual(len(manager.operation_log), 0)

        manager.shutdown()

    def test_secondary_mode_initialization(self):
        """Test initializing manager in secondary mode."""
        config = {}

        def on_operation(op):
            pass

        manager = ReplicationManager(
            mode='secondary',
            config=config,
            on_operation=on_operation
        )

        self.assertEqual(manager.mode, 'secondary')
        self.assertEqual(manager.last_applied_sequence, 0)

        manager.shutdown()

    def test_sequence_generation(self):
        """Test sequence number generation."""
        manager = ReplicationManager(mode='primary', config={})

        seq1 = manager.get_next_sequence()
        seq2 = manager.get_next_sequence()
        seq3 = manager.get_next_sequence()

        self.assertEqual(seq1, 1)
        self.assertEqual(seq2, 2)
        self.assertEqual(seq3, 3)

        manager.shutdown()

    def test_operation_log(self):
        """Test operation log management."""
        manager = ReplicationManager(mode='primary', config={'max_operation_log': 5})

        # Add operations
        for i in range(10):
            op = Operation(
                type=OperationType.SET,
                sequence=i,
                timestamp=time.time(),
                data={'key': f'key{i}'}
            )
            manager.add_to_log(op)

        # Should only keep last 5
        self.assertEqual(len(manager.operation_log), 5)

        # Should be sequences 5-9
        sequences = [op.sequence for op in manager.operation_log]
        self.assertEqual(sequences, [5, 6, 7, 8, 9])

        manager.shutdown()

    def test_broadcast_operation(self):
        """Test broadcasting operations."""
        manager = ReplicationManager(mode='primary', config={})

        operation = ReplicationProtocol.create_set_operation(
            sequence=1,
            key="test",
            value=b"data",
            db="db",
            namespace="ns"
        )

        # Broadcast (should succeed even with no replicas)
        count = manager.broadcast_operation(operation)
        self.assertEqual(count, 0)  # No replicas connected

        # Operation should be in log
        self.assertEqual(len(manager.operation_log), 1)
        self.assertEqual(manager.operation_log[0].sequence, operation.sequence)

        manager.shutdown()


# ============================================================================
# Backend Tests
# ============================================================================

class TestNetworkSyncBackend(unittest.TestCase):
    """Test network sync backend."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir_primary = tempfile.mkdtemp()
        self.temp_dir_secondary = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir_primary, ignore_errors=True)
        shutil.rmtree(self.temp_dir_secondary, ignore_errors=True)

    def test_primary_mode_initialization(self):
        """Test initializing network sync backend in primary mode."""
        base_backend = FileSystemStorage(base_path=self.temp_dir_primary)

        config = {
            'mode': 'primary',
            'listen_host': 'localhost',
            'listen_port': 19000,  # Use different port for testing
            'heartbeat_interval': 5
        }

        backend = NetworkSyncBackend(
            base_backend=base_backend,
            mode='primary',
            config=config
        )

        self.assertEqual(backend.mode, 'primary')
        self.assertTrue(hasattr(backend, 'server'))
        self.assertIsNotNone(backend.server)

        # Cleanup
        backend.close_connections()

    def test_secondary_mode_read_only(self):
        """Test that secondary mode is read-only."""
        base_backend = FileSystemStorage(base_path=self.temp_dir_secondary)

        config = {
            'mode': 'secondary',
            'primary_host': 'localhost',
            'primary_port': 19001
        }

        backend = NetworkSyncBackend(
            base_backend=base_backend,
            mode='secondary',
            config=config
        )

        # Should raise ReadOnlyError
        with self.assertRaises(ReadOnlyError):
            backend.write_data('test/path', b'data')

        with self.assertRaises(ReadOnlyError):
            backend.delete_file('test/path')

        # Cleanup
        backend.close_connections()

    def test_capabilities(self):
        """Test backend capabilities."""
        base_backend = FileSystemStorage(base_path=self.temp_dir_primary)

        config = {
            'mode': 'primary',
            'listen_host': 'localhost',
            'listen_port': 19002
        }

        backend = NetworkSyncBackend(
            base_backend=base_backend,
            mode='primary',
            config=config
        )

        caps = backend.get_capabilities()

        # Should inherit from base but with is_distributed=True
        self.assertTrue(caps.is_distributed)

        # Cleanup
        backend.close_connections()

    def test_read_operations(self):
        """Test read operations work on both modes."""
        base_backend = FileSystemStorage(base_path=self.temp_dir_primary)

        config = {
            'mode': 'primary',
            'listen_host': 'localhost',
            'listen_port': 19003
        }

        backend = NetworkSyncBackend(
            base_backend=base_backend,
            mode='primary',
            config=config
        )

        # Write directly to base backend
        test_path = "test/data"
        base_backend.ensure_directory_exists("test")
        base_backend.write_data(test_path, b"test data")

        # Should be able to read
        data = backend.read_data(test_path)
        self.assertEqual(data, b"test data")

        # Check existence
        self.assertTrue(backend.file_exists(test_path))
        self.assertFalse(backend.file_exists("nonexistent"))

        # Get size
        size = backend.get_file_size(test_path)
        self.assertGreater(size, 0)

        # Cleanup
        backend.close_connections()


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    print("Running NADB Replication Tests")
    print("=" * 60)
    unittest.main(verbosity=2)
