"""
Replication Server for NADB Primary Nodes.

TCP server that accepts connections from secondary nodes and streams operations.
"""

import socket
import threading
import time
import logging
from typing import Optional
import uuid

from replication.manager import ReplicationManager
from replication.connection import ReplicaConnection
from replication.exceptions import ConnectionError as ReplicationConnectionError


class ReplicationServer:
    """
    TCP server for primary node.

    Accepts connections from secondary nodes and manages operation streaming.
    """

    def __init__(
        self,
        host: str,
        port: int,
        manager: ReplicationManager
    ):
        """
        Initialize replication server.

        Args:
            host: Host to bind to (use '0.0.0.0' for all interfaces)
            port: Port to listen on
            manager: ReplicationManager instance (must be in primary mode)
        """
        if manager.mode != "primary":
            raise ValueError("ReplicationServer requires manager in primary mode")

        self.host = host
        self.port = port
        self.manager = manager
        self.logger = logging.getLogger('nadb.replication.server')

        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.accept_thread: Optional[threading.Thread] = None
        self.maintenance_thread: Optional[threading.Thread] = None

        # Connection tracking
        self.active_connections = {}
        self.connections_lock = threading.Lock()

    def start(self):
        """Start the replication server."""
        if self.running:
            self.logger.warning("Server already running")
            return

        try:
            # Create server socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)  # Allow periodic checks

            self.running = True

            # Start accept thread
            self.accept_thread = threading.Thread(
                target=self._accept_connections,
                daemon=True,
                name="ReplicationServerAccept"
            )
            self.accept_thread.start()

            # Start maintenance thread
            self.maintenance_thread = threading.Thread(
                target=self._maintenance_loop,
                daemon=True,
                name="ReplicationServerMaintenance"
            )
            self.maintenance_thread.start()

            self.logger.info(f"Replication server started on {self.host}:{self.port}")

        except Exception as e:
            self.logger.error(f"Failed to start replication server: {e}")
            self.running = False
            raise ReplicationConnectionError(f"Failed to start server: {e}", self.host, self.port)

    def _accept_connections(self):
        """Accept incoming connections from replicas."""
        self.logger.info("Accept thread started")

        while self.running:
            try:
                # Accept with timeout to allow periodic checks
                conn, addr = self.server_socket.accept()

                # Generate replica ID
                replica_id = f"replica-{uuid.uuid4().hex[:8]}"

                self.logger.info(f"Accepted connection from {addr} (ID: {replica_id})")

                # Create replica connection
                replica_conn = ReplicaConnection(replica_id, conn, addr)

                # Register with manager
                self.manager.register_replica(replica_id, replica_conn)

                # Track connection
                with self.connections_lock:
                    self.active_connections[replica_id] = replica_conn

            except socket.timeout:
                # Normal timeout, continue loop
                continue

            except Exception as e:
                if self.running:
                    self.logger.error(f"Error accepting connection: {e}")
                continue

        self.logger.info("Accept thread stopped")

    def _maintenance_loop(self):
        """
        Maintenance loop for:
        - Sending heartbeats
        - Processing send queues
        - Cleaning up dead connections
        """
        self.logger.info("Maintenance thread started")

        while self.running:
            try:
                # Send heartbeats
                self.manager.send_heartbeat()

                # Process send queues
                self.manager.process_replica_queues()

                # Check for dead connections
                self._cleanup_dead_connections()

                # Sleep
                time.sleep(1.0)

            except Exception as e:
                self.logger.error(f"Error in maintenance loop: {e}")
                time.sleep(1.0)

        self.logger.info("Maintenance thread stopped")

    def _cleanup_dead_connections(self):
        """Remove disconnected replicas."""
        dead_replicas = []

        with self.connections_lock:
            for replica_id, conn in list(self.active_connections.items()):
                if not conn.connected:
                    dead_replicas.append(replica_id)
                elif conn.get_lag() > 60:  # 60 seconds without heartbeat
                    self.logger.warning(f"Replica {replica_id} timed out (lag: {conn.get_lag():.1f}s)")
                    conn.disconnect()
                    dead_replicas.append(replica_id)

        for replica_id in dead_replicas:
            self.logger.info(f"Removing dead replica {replica_id}")
            self.manager.unregister_replica(replica_id)
            with self.connections_lock:
                del self.active_connections[replica_id]

    def stop(self):
        """Stop the replication server."""
        if not self.running:
            return

        self.logger.info("Stopping replication server")
        self.running = False

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        # Wait for threads
        if self.accept_thread:
            self.accept_thread.join(timeout=5.0)

        if self.maintenance_thread:
            self.maintenance_thread.join(timeout=5.0)

        # Disconnect all replicas
        with self.connections_lock:
            for replica_id in list(self.active_connections.keys()):
                self.manager.unregister_replica(replica_id)
            self.active_connections.clear()

        self.logger.info("Replication server stopped")

    def get_stats(self) -> dict:
        """
        Get server statistics.

        Returns:
            Statistics dictionary
        """
        with self.connections_lock:
            return {
                'host': self.host,
                'port': self.port,
                'running': self.running,
                'active_connections': len(self.active_connections),
                'replica_stats': self.manager.get_replica_stats()
            }
