"""
Network Sync Storage Backend for NADB.

Wraps another storage backend and adds network replication capabilities.
"""

import logging
from typing import Optional, Dict, Any, List

from storage_backends.base import StorageBackend, BackendCapabilities
from replication.manager import ReplicationManager
from replication.server import ReplicationServer
from replication.client import ReplicationClient
from replication.protocol import Operation, OperationType
from replication.exceptions import ReadOnlyError


class NetworkSyncBackend(StorageBackend):
    """
    Storage backend that adds network replication to another backend.

    Wraps a base backend (fs or redis) and synchronizes operations
    across multiple nodes.

    Modes:
    - primary: Accepts writes and broadcasts to replicas
    - secondary: Read-only, receives updates from primary
    """

    def __init__(
        self,
        base_backend: StorageBackend,
        mode: str,
        config: Dict[str, Any]
    ):
        """
        Initialize network sync backend.

        Args:
            base_backend: Underlying storage backend (fs or redis)
            mode: "primary" or "secondary"
            config: Replication configuration

        Config for primary mode:
            {
                'mode': 'primary',
                'listen_host': '0.0.0.0',
                'listen_port': 9000,
                'heartbeat_interval': 5,
                'max_operation_log': 10000
            }

        Config for secondary mode:
            {
                'mode': 'secondary',
                'primary_host': '192.168.1.10',
                'primary_port': 9000
            }
        """
        self.base_backend = base_backend
        self.mode = mode
        self.config = config
        self.logger = logging.getLogger(f'nadb.storage.network_sync.{mode}')

        # Current database and namespace (for replication context)
        self.current_db = None
        self.current_namespace = None

        # Initialize replication manager
        self.replication_manager = ReplicationManager(
            mode=mode,
            config=config,
            on_operation=self._apply_replicated_operation if mode == "secondary" else None
        )

        # Mode-specific initialization
        if mode == "primary":
            self._init_primary()
        elif mode == "secondary":
            self._init_secondary()
        else:
            raise ValueError(f"Invalid mode: {mode}")

        self.logger.info(f"NetworkSyncBackend initialized in {mode} mode")

    def _init_primary(self):
        """Initialize primary mode."""
        # Start replication server
        listen_host = self.config.get('listen_host', '0.0.0.0')
        listen_port = self.config.get('listen_port', 9000)

        self.server = ReplicationServer(
            listen_host,
            listen_port,
            self.replication_manager
        )
        self.server.start()

        self.logger.info(f"Primary server started on {listen_host}:{listen_port}")

    def _init_secondary(self):
        """Initialize secondary mode."""
        # Start replication client
        primary_host = self.config.get('primary_host')
        primary_port = self.config.get('primary_port', 9000)

        if not primary_host:
            raise ValueError("primary_host required for secondary mode")

        self.client = ReplicationClient(
            primary_host,
            primary_port,
            self.replication_manager
        )
        self.client.start()

        self.logger.info(f"Secondary client connecting to {primary_host}:{primary_port}")

    def set_context(self, db: str, namespace: str):
        """
        Set current database and namespace context.

        Args:
            db: Database name
            namespace: Namespace
        """
        self.current_db = db
        self.current_namespace = namespace

    def _apply_replicated_operation(self, operation: Operation):
        """
        Apply an operation received from primary (secondary mode).

        Args:
            operation: Operation to apply
        """
        try:
            if operation.type == OperationType.SET:
                # Extract data
                data = operation.data
                key = data['key']
                value = data['value']
                path = self._build_path(key, data['db'], data['namespace'])

                # Write to local storage
                self.base_backend.write_data(path, value)

                self.logger.debug(f"Applied SET operation: {key}")

            elif operation.type == OperationType.DELETE:
                # Extract data
                data = operation.data
                key = data['key']
                path = self._build_path(key, data['db'], data['namespace'])

                # Delete from local storage
                self.base_backend.delete_file(path)

                self.logger.debug(f"Applied DELETE operation: {key}")

        except Exception as e:
            self.logger.error(f"Error applying operation {operation.sequence}: {e}")

    def _build_path(self, key: str, db: str, namespace: str) -> str:
        """
        Build path for a key.

        Args:
            key: Key name
            db: Database name
            namespace: Namespace

        Returns:
            Relative path
        """
        # Import hash function from nakv
        from hashlib import blake2b
        h = blake2b(digest_size=16)
        h.update(f"{db}:{namespace}:{key}".encode('utf-8'))
        key_hash = h.hexdigest()

        return f"{db}/{key_hash[0:2]}/{key_hash[2:4]}/{key_hash}"

    def get_capabilities(self) -> BackendCapabilities:
        """
        Get backend capabilities.

        Returns:
            Capabilities of base backend with is_distributed=True
        """
        caps = self.base_backend.get_capabilities()

        # Override to indicate distributed nature
        caps.is_distributed = True

        # Secondary is read-only
        if self.mode == "secondary":
            caps.write_strategy = "immediate"  # No buffering on secondary

        return caps

    def write_data(self, relative_path: str, data: bytes) -> bool:
        """
        Write data to storage.

        Primary: Write locally and broadcast
        Secondary: Reject (read-only)

        Args:
            relative_path: Path for data
            data: Data bytes

        Returns:
            True if successful

        Raises:
            ReadOnlyError: If in secondary mode
        """
        if self.mode == "secondary":
            raise ReadOnlyError("Cannot write to secondary replica")

        # Write to base backend
        success = self.base_backend.write_data(relative_path, data)

        if success and self.current_db and self.current_namespace:
            # Extract key from path (simplified - actual key would need to be passed)
            # For now, we'll create operation when we have the key context
            pass

        return success

    def write_with_replication(
        self,
        relative_path: str,
        data: bytes,
        key: str,
        tags: Optional[List[str]] = None,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Write data with full replication.

        Args:
            relative_path: Path for data
            data: Data bytes
            key: Original key
            tags: Optional tags
            ttl: Optional TTL

        Returns:
            True if successful

        Raises:
            ReadOnlyError: If in secondary mode
        """
        if self.mode == "secondary":
            raise ReadOnlyError("Cannot write to secondary replica")

        # Write to base backend
        success = self.base_backend.write_data(relative_path, data)

        if success and self.current_db and self.current_namespace:
            # Broadcast to replicas
            self.replication_manager.create_and_broadcast_set_operation(
                key=key,
                value=data,
                db=self.current_db,
                namespace=self.current_namespace,
                tags=tags,
                ttl=ttl
            )

        return success

    def read_data(self, relative_path: str) -> Optional[bytes]:
        """
        Read data from storage.

        Both modes: Read from local storage

        Args:
            relative_path: Path for data

        Returns:
            Data bytes or None
        """
        return self.base_backend.read_data(relative_path)

    def delete_file(self, relative_path: str) -> bool:
        """
        Delete data from storage.

        Primary: Delete locally and broadcast
        Secondary: Reject (read-only)

        Args:
            relative_path: Path for data

        Returns:
            True if successful

        Raises:
            ReadOnlyError: If in secondary mode
        """
        if self.mode == "secondary":
            raise ReadOnlyError("Cannot delete from secondary replica")

        return self.base_backend.delete_file(relative_path)

    def delete_with_replication(
        self,
        relative_path: str,
        key: str
    ) -> bool:
        """
        Delete data with full replication.

        Args:
            relative_path: Path for data
            key: Original key

        Returns:
            True if successful

        Raises:
            ReadOnlyError: If in secondary mode
        """
        if self.mode == "secondary":
            raise ReadOnlyError("Cannot delete from secondary replica")

        # Delete from base backend
        success = self.base_backend.delete_file(relative_path)

        if success and self.current_db and self.current_namespace:
            # Broadcast to replicas
            self.replication_manager.create_and_broadcast_delete_operation(
                key=key,
                db=self.current_db,
                namespace=self.current_namespace
            )

        return success

    def file_exists(self, relative_path: str) -> bool:
        """Check if file exists."""
        return self.base_backend.file_exists(relative_path)

    def get_file_size(self, relative_path: str) -> int:
        """Get file size."""
        return self.base_backend.get_file_size(relative_path)

    def get_full_path(self, relative_path: str) -> str:
        """Get full path."""
        return self.base_backend.get_full_path(relative_path)

    def ensure_directory_exists(self, path: str) -> bool:
        """Ensure directory exists."""
        return self.base_backend.ensure_directory_exists(path)

    # Metadata methods - delegate to base backend

    def set_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Set metadata."""
        if self.mode == "secondary":
            # Allow metadata writes on secondary (they come from replication)
            pass

        return self.base_backend.set_metadata(metadata)

    def get_metadata(self, key: str, db: str, namespace: str) -> Optional[Dict[str, Any]]:
        """Get metadata."""
        return self.base_backend.get_metadata(key, db, namespace)

    def delete_metadata(self, key: str, db: str, namespace: str) -> bool:
        """Delete metadata."""
        if self.mode == "secondary":
            raise ReadOnlyError("Cannot delete metadata from secondary replica")

        return self.base_backend.delete_metadata(key, db, namespace)

    def query_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Query metadata."""
        return self.base_backend.query_metadata(query)

    def close_connections(self) -> None:
        """Close connections."""
        # Shutdown replication
        if self.mode == "primary" and hasattr(self, 'server'):
            self.server.stop()
        elif self.mode == "secondary" and hasattr(self, 'client'):
            self.client.stop()

        self.replication_manager.shutdown()

        # Close base backend
        self.base_backend.close_connections()

    def get_replication_stats(self) -> Dict:
        """
        Get replication statistics.

        Returns:
            Statistics dictionary
        """
        stats = self.replication_manager.get_stats()

        if self.mode == "primary" and hasattr(self, 'server'):
            stats['server'] = self.server.get_stats()
        elif self.mode == "secondary" and hasattr(self, 'client'):
            stats['client'] = self.client.get_stats()

        return stats
