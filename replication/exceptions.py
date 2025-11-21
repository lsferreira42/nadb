"""
Replication-specific exceptions for NADB.

This module defines all exceptions that can be raised during
replication operations.
"""


class ReplicationError(Exception):
    """Base exception for all replication errors."""
    pass


class ReadOnlyError(ReplicationError):
    """Raised when attempting to write to a read-only replica."""

    def __init__(self, message="Cannot perform write operation on read-only replica"):
        self.message = message
        super().__init__(self.message)


class ConnectionError(ReplicationError):
    """Raised when connection to primary or replica fails."""

    def __init__(self, message, host=None, port=None):
        self.message = message
        self.host = host
        self.port = port
        super().__init__(self.message)

    def __str__(self):
        if self.host and self.port:
            return f"{self.message} (host={self.host}, port={self.port})"
        return self.message


class ProtocolError(ReplicationError):
    """Raised when protocol validation fails."""

    def __init__(self, message, operation=None):
        self.message = message
        self.operation = operation
        super().__init__(self.message)


class SyncError(ReplicationError):
    """Raised when synchronization fails."""

    def __init__(self, message, sequence=None):
        self.message = message
        self.sequence = sequence
        super().__init__(self.message)

    def __str__(self):
        if self.sequence is not None:
            return f"{self.message} (sequence={self.sequence})"
        return self.message


class ReplicaTimeoutError(ReplicationError):
    """Raised when replica doesn't respond within timeout."""

    def __init__(self, replica_id, timeout):
        self.replica_id = replica_id
        self.timeout = timeout
        self.message = f"Replica {replica_id} timed out after {timeout}s"
        super().__init__(self.message)


class ChecksumMismatchError(ProtocolError):
    """Raised when operation checksum doesn't match."""

    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
        self.message = f"Checksum mismatch: expected {expected}, got {actual}"
        super().__init__(self.message)
