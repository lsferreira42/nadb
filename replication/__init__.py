"""
NADB Network Replication Module

This module provides network-based replication capabilities for NADB,
allowing data and metadata synchronization across multiple nodes.

Key Components:
- ReplicationManager: Core replication logic for primary and secondary modes
- ReplicationServer: TCP server for primary nodes
- ReplicationClient: TCP client for secondary nodes
- ReplicationProtocol: Serialization and validation of operations
"""

from replication.exceptions import (
    ReplicationError,
    ReadOnlyError,
    ConnectionError,
    ProtocolError,
    SyncError
)

from replication.protocol import (
    ReplicationProtocol,
    Operation,
    OperationType
)

from replication.manager import ReplicationManager
from replication.server import ReplicationServer
from replication.client import ReplicationClient

__all__ = [
    'ReplicationManager',
    'ReplicationServer',
    'ReplicationClient',
    'ReplicationProtocol',
    'Operation',
    'OperationType',
    'ReplicationError',
    'ReadOnlyError',
    'ConnectionError',
    'ProtocolError',
    'SyncError'
]

__version__ = '1.0.0'
