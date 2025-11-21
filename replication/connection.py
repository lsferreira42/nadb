"""
Connection management for NADB replication.

Handles individual TCP connections between primary and secondary nodes.
"""

import socket
import threading
import time
import logging
from typing import Optional, Callable
from queue import Queue, Empty

from replication.protocol import ReplicationProtocol, Operation
from replication.exceptions import ConnectionError as ReplicationConnectionError, ProtocolError


class ReplicaConnection:
    """
    Represents a connection to a replica (used by primary).

    Manages sending operations to a single replica with buffering
    and error handling.
    """

    def __init__(self, replica_id: str, sock: socket.socket, address: tuple):
        """
        Initialize replica connection.

        Args:
            replica_id: Unique identifier for this replica
            sock: Connected socket
            address: (host, port) tuple
        """
        self.replica_id = replica_id
        self.socket = sock
        self.address = address
        self.connected = True
        self.last_heartbeat = time.time()
        self.last_sequence = 0
        self.lock = threading.RLock()
        self.send_queue = Queue(maxsize=1000)
        self.logger = logging.getLogger(f'nadb.replication.replica.{replica_id}')

        # Statistics
        self.operations_sent = 0
        self.bytes_sent = 0
        self.errors = 0

        # Configure socket
        self.socket.settimeout(30.0)  # 30 second timeout

    def send_operation(self, operation: Operation, blocking: bool = True) -> bool:
        """
        Send an operation to the replica.

        Args:
            operation: Operation to send
            blocking: If True, block until sent; if False, queue it

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.connected:
            return False

        try:
            # Serialize operation
            data = ReplicationProtocol.serialize(operation)

            if blocking:
                # Send immediately
                return self._send_data(data)
            else:
                # Queue for sending
                try:
                    self.send_queue.put_nowait((operation, data))
                    return True
                except:
                    self.logger.warning(f"Send queue full for replica {self.replica_id}")
                    return False

        except Exception as e:
            self.logger.error(f"Error sending operation to {self.replica_id}: {e}")
            self.errors += 1
            return False

    def _send_data(self, data: bytes) -> bool:
        """
        Send raw data to replica.

        Args:
            data: Bytes to send

        Returns:
            True if sent successfully
        """
        with self.lock:
            if not self.connected:
                return False

            try:
                # Send all data
                self.socket.sendall(data)
                self.operations_sent += 1
                self.bytes_sent += len(data)
                return True

            except socket.timeout:
                self.logger.error(f"Timeout sending to replica {self.replica_id}")
                self.disconnect()
                return False

            except Exception as e:
                self.logger.error(f"Error sending to replica {self.replica_id}: {e}")
                self.disconnect()
                return False

    def process_send_queue(self):
        """Process queued operations (call periodically)."""
        operations_sent = 0
        max_batch = 100

        try:
            while operations_sent < max_batch:
                try:
                    operation, data = self.send_queue.get_nowait()
                    if self._send_data(data):
                        self.last_sequence = operation.sequence
                        operations_sent += 1
                    else:
                        # Failed to send, put back
                        self.send_queue.put((operation, data))
                        break
                except Empty:
                    break

        except Exception as e:
            self.logger.error(f"Error processing send queue: {e}")

    def update_heartbeat(self):
        """Update last heartbeat timestamp."""
        self.last_heartbeat = time.time()

    def get_lag(self) -> float:
        """
        Get time since last heartbeat.

        Returns:
            Seconds since last heartbeat
        """
        return time.time() - self.last_heartbeat

    def disconnect(self):
        """Disconnect from replica."""
        with self.lock:
            if self.connected:
                self.connected = False
                try:
                    self.socket.close()
                except:
                    pass
                self.logger.info(f"Disconnected from replica {self.replica_id}")

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            'replica_id': self.replica_id,
            'address': self.address,
            'connected': self.connected,
            'last_heartbeat': self.last_heartbeat,
            'lag_seconds': self.get_lag(),
            'last_sequence': self.last_sequence,
            'operations_sent': self.operations_sent,
            'bytes_sent': self.bytes_sent,
            'errors': self.errors,
            'queue_size': self.send_queue.qsize()
        }


class PrimaryConnection:
    """
    Represents a connection to the primary (used by secondary).

    Manages receiving operations from the primary with reconnection logic.
    """

    def __init__(self, host: str, port: int, on_operation: Callable[[Operation], None]):
        """
        Initialize primary connection.

        Args:
            host: Primary host
            port: Primary port
            on_operation: Callback for received operations
        """
        self.host = host
        self.port = port
        self.on_operation = on_operation
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.lock = threading.RLock()
        self.logger = logging.getLogger('nadb.replication.primary')

        # Reconnection parameters
        self.reconnect_interval = 5.0
        self.last_reconnect_attempt = 0
        self.reconnect_backoff = 1.0
        self.max_backoff = 60.0

        # Statistics
        self.operations_received = 0
        self.bytes_received = 0
        self.reconnections = 0
        self.last_operation_time = time.time()

        # Receive buffer
        self.recv_buffer = bytearray()

    def connect(self) -> bool:
        """
        Connect to primary.

        Returns:
            True if connected successfully
        """
        with self.lock:
            if self.connected:
                return True

            # Check if we should throttle reconnection
            now = time.time()
            if now - self.last_reconnect_attempt < self.reconnect_backoff:
                return False

            self.last_reconnect_attempt = now

            try:
                # Create socket
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(10.0)

                # Connect
                self.socket.connect((self.host, self.port))
                self.connected = True
                self.reconnect_backoff = 1.0  # Reset backoff
                self.reconnections += 1

                self.logger.info(f"Connected to primary at {self.host}:{self.port}")
                return True

            except socket.timeout:
                self.logger.error(f"Timeout connecting to primary {self.host}:{self.port}")
                self._increase_backoff()
                return False

            except Exception as e:
                self.logger.error(f"Failed to connect to primary: {e}")
                self._increase_backoff()
                return False

    def _increase_backoff(self):
        """Increase reconnection backoff time."""
        self.reconnect_backoff = min(self.reconnect_backoff * 2, self.max_backoff)

    def receive_operations(self) -> bool:
        """
        Receive and process operations from primary.

        Returns:
            True if operations received, False if disconnected
        """
        if not self.connected:
            return False

        try:
            # Receive data
            data = self.socket.recv(4096)

            if not data:
                # Connection closed
                self.logger.warning("Primary closed connection")
                self.disconnect()
                return False

            # Add to buffer
            self.recv_buffer.extend(data)
            self.bytes_received += len(data)

            # Process complete operations
            self._process_buffer()

            return True

        except socket.timeout:
            # Timeout is not necessarily an error, just no data
            return True

        except Exception as e:
            self.logger.error(f"Error receiving from primary: {e}")
            self.disconnect()
            return False

    def _process_buffer(self):
        """Process operations in receive buffer."""
        while len(self.recv_buffer) >= 4:
            # Check if we have a complete operation
            length = int.from_bytes(self.recv_buffer[:4], byteorder='big')

            if len(self.recv_buffer) < 4 + length:
                # Incomplete operation, wait for more data
                break

            try:
                # Extract operation data
                operation_data = bytes(self.recv_buffer[:4 + length])

                # Deserialize
                operation = ReplicationProtocol.deserialize(operation_data)

                # Process operation
                self.on_operation(operation)
                self.operations_received += 1
                self.last_operation_time = time.time()

                # Remove from buffer
                del self.recv_buffer[:4 + length]

            except ProtocolError as e:
                self.logger.error(f"Protocol error: {e}")
                # Skip this operation
                del self.recv_buffer[:4 + length]

            except Exception as e:
                self.logger.error(f"Error processing operation: {e}")
                # Clear buffer to recover
                self.recv_buffer.clear()
                break

    def disconnect(self):
        """Disconnect from primary."""
        with self.lock:
            if self.connected:
                self.connected = False
                try:
                    if self.socket:
                        self.socket.close()
                except:
                    pass
                self.logger.info("Disconnected from primary")

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            'host': self.host,
            'port': self.port,
            'connected': self.connected,
            'operations_received': self.operations_received,
            'bytes_received': self.bytes_received,
            'reconnections': self.reconnections,
            'last_operation_time': self.last_operation_time,
            'seconds_since_last_operation': time.time() - self.last_operation_time
        }
