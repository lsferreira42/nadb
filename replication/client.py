"""
Replication Client for NADB Secondary Nodes.

TCP client that connects to primary and receives operation stream.
"""

import threading
import time
import logging
from typing import Optional

from replication.manager import ReplicationManager


class ReplicationClient:
    """
    TCP client for secondary node.

    Connects to primary node and receives operation stream.
    """

    def __init__(
        self,
        primary_host: str,
        primary_port: int,
        manager: ReplicationManager
    ):
        """
        Initialize replication client.

        Args:
            primary_host: Primary node host
            primary_port: Primary node port
            manager: ReplicationManager instance (must be in secondary mode)
        """
        if manager.mode != "secondary":
            raise ValueError("ReplicationClient requires manager in secondary mode")

        self.primary_host = primary_host
        self.primary_port = primary_port
        self.manager = manager
        self.logger = logging.getLogger('nadb.replication.client')

        self.running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.reconnect_interval = 5.0

    def start(self):
        """Start the replication client."""
        if self.running:
            self.logger.warning("Client already running")
            return

        self.running = True

        # Start receive thread
        self.receive_thread = threading.Thread(
            target=self._receive_loop,
            daemon=True,
            name="ReplicationClientReceive"
        )
        self.receive_thread.start()

        self.logger.info(f"Replication client started (primary: {self.primary_host}:{self.primary_port})")

    def _receive_loop(self):
        """Main receive loop with automatic reconnection."""
        self.logger.info("Receive thread started")

        while self.running:
            try:
                # Try to connect if not connected
                if not self.manager.primary_connection or not self.manager.primary_connection.connected:
                    self.logger.info(f"Attempting to connect to primary {self.primary_host}:{self.primary_port}")

                    if self.manager.connect_to_primary(self.primary_host, self.primary_port):
                        self.logger.info("Connected to primary")
                    else:
                        self.logger.debug("Connection attempt failed, will retry")
                        time.sleep(self.reconnect_interval)
                        continue

                # Receive operations
                if not self.manager.receive_from_primary():
                    self.logger.warning("Disconnected from primary")
                    time.sleep(self.reconnect_interval)
                    continue

                # Small sleep to prevent busy-waiting
                time.sleep(0.01)

            except Exception as e:
                self.logger.error(f"Error in receive loop: {e}")
                time.sleep(self.reconnect_interval)

        self.logger.info("Receive thread stopped")

    def stop(self):
        """Stop the replication client."""
        if not self.running:
            return

        self.logger.info("Stopping replication client")
        self.running = False

        # Disconnect from primary
        if self.manager.primary_connection:
            self.manager.primary_connection.disconnect()

        # Wait for thread
        if self.receive_thread:
            self.receive_thread.join(timeout=5.0)

        self.logger.info("Replication client stopped")

    def get_stats(self) -> dict:
        """
        Get client statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            'primary_host': self.primary_host,
            'primary_port': self.primary_port,
            'running': self.running
        }

        primary_stats = self.manager.get_primary_stats()
        if primary_stats:
            stats.update(primary_stats)

        return stats

    def is_connected(self) -> bool:
        """
        Check if connected to primary.

        Returns:
            True if connected
        """
        return (
            self.manager.primary_connection is not None and
            self.manager.primary_connection.connected
        )
