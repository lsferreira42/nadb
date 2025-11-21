"""
Abstract Base Class for Storage Backends in NADB Key-Value Store.

This module defines the interface that all storage backends must implement,
ensuring consistency across different storage implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Literal
from dataclasses import dataclass
import zlib

# Constants for compression
COMPRESS_MIN_SIZE = 1024  # Only compress files larger than 1KB
COMPRESS_LEVEL = 6  # Medium compression (range is 0-9)


@dataclass
class BackendCapabilities:
    """
    Describes the capabilities and characteristics of a storage backend.

    This allows KeyValueStore to adapt its behavior based on what
    the backend supports natively.
    """
    # Core capabilities
    supports_buffering: bool = True
    """Backend can benefit from in-memory buffering before writes"""

    supports_native_ttl: bool = False
    """Backend has native TTL/expiration support"""

    supports_transactions: bool = False
    """Backend has native transaction support (ACID)"""

    supports_metadata: bool = False
    """Backend can store metadata alongside data (tags, timestamps, etc)"""

    supports_atomic_writes: bool = True
    """Backend guarantees atomic write operations"""

    # Write strategy
    write_strategy: Literal["immediate", "buffered", "auto"] = "auto"
    """
    Preferred write strategy:
    - immediate: Write directly to storage (Redis, databases)
    - buffered: Use in-memory buffer with periodic flush (filesystem)
    - auto: Let KeyValueStore decide based on other capabilities
    """

    # Performance characteristics
    is_distributed: bool = False
    """Backend is distributed/networked (affects latency expectations)"""

    is_persistent: bool = True
    """Backend persists data across restarts"""

    supports_compression: bool = True
    """Backend supports or benefits from compression"""

    # Query capabilities
    supports_native_queries: bool = False
    """Backend can handle complex queries natively"""

    max_value_size_bytes: Optional[int] = None
    """Maximum value size supported (None = unlimited)"""


class StorageBackend(ABC):
    """
    Abstract base class for all NADB storage backends.

    All storage backends must implement these methods to ensure
    consistent behavior across different storage implementations.
    """

    @abstractmethod
    def get_capabilities(self) -> BackendCapabilities:
        """
        Get the capabilities of this storage backend.

        Returns:
            BackendCapabilities describing what this backend supports
        """
        pass

    @abstractmethod
    def write_data(self, relative_path: str, data: bytes) -> bool:
        """
        Write data to storage.

        Args:
            relative_path: Path/key for the data
            data: Binary data to store

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def read_data(self, relative_path: str) -> Optional[bytes]:
        """
        Read data from storage.

        Args:
            relative_path: Path/key for the data

        Returns:
            Binary data if found, None otherwise
        """
        pass

    @abstractmethod
    def delete_file(self, relative_path: str) -> bool:
        """
        Delete data from storage.

        Args:
            relative_path: Path/key for the data

        Returns:
            True if successful or data didn't exist, False on error
        """
        pass

    @abstractmethod
    def file_exists(self, relative_path: str) -> bool:
        """
        Check if data exists in storage.

        Args:
            relative_path: Path/key for the data

        Returns:
            True if data exists, False otherwise
        """
        pass

    @abstractmethod
    def get_file_size(self, relative_path: str) -> int:
        """
        Get size of data in storage.

        Args:
            relative_path: Path/key for the data

        Returns:
            Size in bytes, 0 if data doesn't exist
        """
        pass

    @abstractmethod
    def get_full_path(self, relative_path: str) -> str:
        """
        Get the full path/key for the data.

        Args:
            relative_path: Relative path/key

        Returns:
            Full path/key in storage
        """
        pass

    @abstractmethod
    def ensure_directory_exists(self, path: str) -> bool:
        """
        Ensure the directory/namespace exists.

        Args:
            path: Path to ensure exists

        Returns:
            True if exists or created successfully
        """
        pass

    def compress_data(self, data: bytes, compression_enabled: bool) -> bytes:
        """
        Compress data using zlib if appropriate.

        Args:
            data: Binary data to potentially compress
            compression_enabled: Whether compression is enabled

        Returns:
            Compressed data with header or original data
        """
        if not compression_enabled or len(data) <= COMPRESS_MIN_SIZE:
            return data

        compressed = zlib.compress(data, COMPRESS_LEVEL)
        return b'CMP:' + compressed

    def decompress_data(self, data: bytes) -> bytes:
        """
        Decompress data if it was compressed.

        Args:
            data: Potentially compressed data

        Returns:
            Decompressed data
        """
        if not data or not self._is_compressed(data):
            return data

        compressed_data = data[4:]
        return zlib.decompress(compressed_data)

    def _is_compressed(self, data: bytes) -> bool:
        """Check if data has the compression header."""
        return data and data.startswith(b'CMP:')

    def close_connections(self) -> None:
        """
        Close any open connections.
        Override in subclasses that need connection management.
        """
        pass

    # Optional metadata methods - only needed if supports_metadata=True
    def set_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Store metadata (optional - only if backend supports_metadata).

        Args:
            metadata: Dictionary containing metadata

        Returns:
            True if successful, False otherwise
        """
        raise NotImplementedError("Backend does not support metadata storage")

    def get_metadata(self, key: str, db: str, namespace: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a key (optional - only if backend supports_metadata).

        Args:
            key: The data key
            db: Database name
            namespace: Namespace

        Returns:
            Metadata dictionary or None if not found
        """
        raise NotImplementedError("Backend does not support metadata storage")

    def delete_metadata(self, key: str, db: str, namespace: str) -> bool:
        """
        Delete metadata for a key (optional - only if backend supports_metadata).

        Args:
            key: The data key
            db: Database name
            namespace: Namespace

        Returns:
            True if successful, False otherwise
        """
        raise NotImplementedError("Backend does not support metadata storage")

    def query_metadata(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Query metadata based on criteria (optional - only if backend supports_metadata).

        Args:
            query: Dictionary containing query parameters

        Returns:
            List of matching metadata dictionaries
        """
        raise NotImplementedError("Backend does not support metadata queries")
