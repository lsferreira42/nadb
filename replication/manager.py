"""
Replication Manager for NADB.

Core component that manages replication logic for both primary and secondary modes.
"""

import threading
import time
import logging
from collections import deque
from typing import Dict, List, Optional, Callable, Literal
from datetime import datetime

from replication.protocol import (
    ReplicationProtocol,
    Operation,
    OperationType
)
from replication.connection import ReplicaConnection, PrimaryConnection
from replication.exceptions import ReadOnlyError, SyncError


class ReplicationManager:
    """
    Manages replication for NADB.

    Supports two modes:
    - primary: Accepts writes and broadcasts to replicas
    - secondary: Receives operations from primary (read-only)
    """

    def __init__(
        self,
        mode: Literal["primary", "secondary"],
        config: Dict,
        on_operation: Optional[Callable[[Operation], None]] = None
    ):
        """
        Initialize replication manager.

        Args:
            mode: "primary" or "secondary"
            config: Configuration dictionary
            on_operation: Callback for applying operations (secondary mode)
        """
        self.mode = mode
        self.config = config
        self.on_operation = on_operation
        self.logger = logging.getLogger(f'nadb.replication.manager.{mode}')

        # Sequence tracking
        self.sequence_number = 0
        self.sequence_lock = threading.Lock()

        # Operation log for replay/recovery
        max_log_size = config.get('max_operation_log', 10000)
        self.operation_log = deque(maxlen=max_log_size)
        self.log_lock = threading.RLock()

        # Mode-specific initialization
        if mode == "primary":
            self._init_primary()
        elif mode == "secondary":
            self._init_secondary()
        else:
            raise ValueError(f"Invalid replication mode: {mode}")

        self.logger.info(f"ReplicationManager initialized in {mode} mode")

    def _init_primary(self):
        """Initialize primary-specific state."""
        self.replicas: Dict[str, ReplicaConnection] = {}
        self.replicas_lock = threading.RLock()

        # Heartbeat configuration
        self.heartbeat_interval = self.config.get('heartbeat_interval', 5.0)
        self.last_heartbeat = time.time()

        # Broadcast configuration
        self.broadcast_async = self.config.get('broadcast_async', True)

    def _init_secondary(self):
        """Initialize secondary-specific state."""
        self.primary_connection: Optional[PrimaryConnection] = None
        self.last_applied_sequence = 0
        self.is_syncing = False

        # Track applied operations
        self.operations_applied = 0

    def get_next_sequence(self) -> int:
        """
        Get next sequence number (thread-safe).

        Returns:
            Next sequence number
        """
        with self.sequence_lock:
            self.sequence_number += 1
            return self.sequence_number

    def add_to_log(self, operation: Operation):
        """
        Add operation to log.

        Args:
            operation: Operation to log
        """
        with self.log_lock:
            self.operation_log.append(operation)

    def get_operations_from_sequence(self, from_sequence: int) -> List[Operation]:
        """
        Get operations starting from a sequence number.

        Args:
            from_sequence: Starting sequence number

        Returns:
            List of operations
        """
        with self.log_lock:
            operations = []
            for op in self.operation_log:
                if op.sequence >= from_sequence:
                    operations.append(op)
            return operations

    # Primary mode methods

    def register_replica(self, replica_id: str, connection: ReplicaConnection) -> bool:
        """
        Register a new replica connection.

        Args:
            replica_id: Unique replica identifier
            connection: ReplicaConnection object

        Returns:
            True if registered successfully
        """
        if self.mode != "primary":
            raise RuntimeError("Can only register replicas in primary mode")

        with self.replicas_lock:
            if replica_id in self.replicas:
                self.logger.warning(f"Replica {replica_id} already registered, replacing")
                old_conn = self.replicas[replica_id]
                old_conn.disconnect()

            self.replicas[replica_id] = connection
            self.logger.info(f"Registered replica {replica_id} from {connection.address}")

            # Send recent operations to new replica for catch-up
            self._send_catchup_operations(connection)

            return True

    def unregister_replica(self, replica_id: str):
        """
        Unregister a replica.

        Args:
            replica_id: Replica identifier
        """
        if self.mode != "primary":
            return

        with self.replicas_lock:
            if replica_id in self.replicas:
                connection = self.replicas[replica_id]
                connection.disconnect()
                del self.replicas[replica_id]
                self.logger.info(f"Unregistered replica {replica_id}")

    def _send_catchup_operations(self, connection: ReplicaConnection):
        """
        Send recent operations to a new replica.

        Args:
            connection: New replica connection
        """
        with self.log_lock:
            # Send last 1000 operations
            operations = list(self.operation_log)[-1000:]

            self.logger.info(f"Sending {len(operations)} catch-up operations to {connection.replica_id}")

            for operation in operations:
                connection.send_operation(operation, blocking=False)

    def broadcast_operation(self, operation: Operation) -> int:
        """
        Broadcast an operation to all replicas.

        Args:
            operation: Operation to broadcast

        Returns:
            Number of replicas that received the operation
        """
        if self.mode != "primary":
            raise RuntimeError("Can only broadcast in primary mode")

        # Add to log
        self.add_to_log(operation)

        # Send to all replicas
        success_count = 0
        failed_replicas = []

        with self.replicas_lock:
            for replica_id, connection in list(self.replicas.items()):
                if connection.connected:
                    if connection.send_operation(operation, blocking=not self.broadcast_async):
                        success_count += 1
                    else:
                        failed_replicas.append(replica_id)
                else:
                    failed_replicas.append(replica_id)

        # Remove failed replicas
        for replica_id in failed_replicas:
            self.logger.warning(f"Replica {replica_id} failed, unregistering")
            self.unregister_replica(replica_id)

        return success_count

    def create_and_broadcast_set_operation(
        self,
        key: str,
        value: bytes,
        db: str,
        namespace: str,
        tags: Optional[List[str]] = None,
        ttl: Optional[int] = None
    ) -> Operation:
        """
        Create and broadcast a SET operation.

        Args:
            key: Key to set
            value: Value bytes
            db: Database name
            namespace: Namespace
            tags: Optional tags
            ttl: Optional TTL

        Returns:
            Created operation
        """
        if self.mode != "primary":
            raise ReadOnlyError()

        sequence = self.get_next_sequence()
        operation = ReplicationProtocol.create_set_operation(
            sequence, key, value, db, namespace, tags, ttl
        )

        self.broadcast_operation(operation)
        return operation

    def create_and_broadcast_delete_operation(
        self,
        key: str,
        db: str,
        namespace: str
    ) -> Operation:
        """
        Create and broadcast a DELETE operation.

        Args:
            key: Key to delete
            db: Database name
            namespace: Namespace

        Returns:
            Created operation
        """
        if self.mode != "primary":
            raise ReadOnlyError()

        sequence = self.get_next_sequence()
        operation = ReplicationProtocol.create_delete_operation(
            sequence, key, db, namespace
        )

        self.broadcast_operation(operation)
        return operation

    def send_heartbeat(self):
        """Send heartbeat to all replicas."""
        if self.mode != "primary":
            return

        now = time.time()
        if now - self.last_heartbeat < self.heartbeat_interval:
            return

        sequence = self.get_next_sequence()
        heartbeat = ReplicationProtocol.create_heartbeat_operation(sequence)

        with self.replicas_lock:
            for connection in self.replicas.values():
                connection.send_operation(heartbeat, blocking=False)
                connection.update_heartbeat()

        self.last_heartbeat = now

    def process_replica_queues(self):
        """Process send queues for all replicas."""
        if self.mode != "primary":
            return

        with self.replicas_lock:
            for connection in list(self.replicas.values()):
                connection.process_send_queue()

    def get_replica_stats(self) -> List[Dict]:
        """
        Get statistics for all replicas.

        Returns:
            List of replica statistics
        """
        if self.mode != "primary":
            return []

        with self.replicas_lock:
            return [conn.get_stats() for conn in self.replicas.values()]

    # Secondary mode methods

    def connect_to_primary(self, host: str, port: int) -> bool:
        """
        Connect to primary node.

        Args:
            host: Primary host
            port: Primary port

        Returns:
            True if connected
        """
        if self.mode != "secondary":
            raise RuntimeError("Can only connect to primary in secondary mode")

        if self.primary_connection is None:
            self.primary_connection = PrimaryConnection(
                host, port, self._handle_received_operation
            )

        return self.primary_connection.connect()

    def _handle_received_operation(self, operation: Operation):
        """
        Handle an operation received from primary.

        Args:
            operation: Received operation
        """
        try:
            # Skip heartbeats
            if operation.type == OperationType.HEARTBEAT:
                return

            # Check sequence
            if operation.sequence <= self.last_applied_sequence:
                self.logger.debug(f"Skipping already applied operation {operation.sequence}")
                return

            # Check for gap in sequence
            if operation.sequence > self.last_applied_sequence + 1:
                self.logger.warning(
                    f"Sequence gap detected: expected {self.last_applied_sequence + 1}, "
                    f"got {operation.sequence}"
                )
                # Request sync (TODO: implement sync request mechanism)

            # Apply operation
            if self.on_operation:
                self.on_operation(operation)

            self.last_applied_sequence = operation.sequence
            self.operations_applied += 1
            self.add_to_log(operation)

        except Exception as e:
            self.logger.error(f"Error handling operation {operation.sequence}: {e}")

    def receive_from_primary(self) -> bool:
        """
        Receive operations from primary.

        Returns:
            True if receiving, False if disconnected
        """
        if self.mode != "secondary":
            return False

        if self.primary_connection is None:
            return False

        if not self.primary_connection.connected:
            # Try to reconnect
            return self.connect_to_primary(
                self.primary_connection.host,
                self.primary_connection.port
            )

        return self.primary_connection.receive_operations()

    def get_primary_stats(self) -> Optional[Dict]:
        """
        Get primary connection statistics.

        Returns:
            Statistics dictionary or None
        """
        if self.mode != "secondary" or self.primary_connection is None:
            return None

        stats = self.primary_connection.get_stats()
        stats['last_applied_sequence'] = self.last_applied_sequence
        stats['operations_applied'] = self.operations_applied
        return stats

    # Common methods

    def get_stats(self) -> Dict:
        """
        Get replication statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            'mode': self.mode,
            'sequence_number': self.sequence_number,
            'operation_log_size': len(self.operation_log)
        }

        if self.mode == "primary":
            stats['replicas'] = self.get_replica_stats()
            stats['replica_count'] = len(self.replicas)

        elif self.mode == "secondary":
            primary_stats = self.get_primary_stats()
            if primary_stats:
                stats['primary'] = primary_stats

        return stats

    def shutdown(self):
        """Shutdown replication manager."""
        self.logger.info("Shutting down replication manager")

        if self.mode == "primary":
            with self.replicas_lock:
                for replica_id in list(self.replicas.keys()):
                    self.unregister_replica(replica_id)

        elif self.mode == "secondary":
            if self.primary_connection:
                self.primary_connection.disconnect()

        self.logger.info("Replication manager shut down")
