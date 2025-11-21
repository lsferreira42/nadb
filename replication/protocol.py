"""
Replication Protocol for NADB.

This module handles serialization, deserialization, and validation
of replication operations between primary and secondary nodes.
"""

import json
import base64
import hashlib
import time
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from replication.exceptions import ProtocolError, ChecksumMismatchError


class OperationType(Enum):
    """Types of operations that can be replicated."""
    SET = "SET"
    DELETE = "DELETE"
    SET_TTL = "SET_TTL"
    FLUSH = "FLUSH"
    METADATA = "METADATA"
    HEARTBEAT = "HEARTBEAT"
    SYNC_REQUEST = "SYNC_REQUEST"
    SYNC_RESPONSE = "SYNC_RESPONSE"


@dataclass
class Operation:
    """Represents a single replication operation."""
    type: OperationType
    sequence: int
    timestamp: float
    data: Dict[str, Any]
    checksum: Optional[str] = None

    def __post_init__(self):
        """Ensure type is an OperationType enum."""
        if isinstance(self.type, str):
            self.type = OperationType(self.type)

    def to_dict(self) -> Dict[str, Any]:
        """Convert operation to dictionary."""
        return {
            'type': self.type.value,
            'sequence': self.sequence,
            'timestamp': self.timestamp,
            'data': self.data,
            'checksum': self.checksum
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Operation':
        """Create operation from dictionary."""
        return cls(
            type=OperationType(data['type']),
            sequence=data['sequence'],
            timestamp=data['timestamp'],
            data=data['data'],
            checksum=data.get('checksum')
        )


class ReplicationProtocol:
    """
    Handles serialization and validation of replication operations.

    Protocol format (JSON over TCP):
    {
        "type": "SET|DELETE|SET_TTL|FLUSH|METADATA|HEARTBEAT",
        "sequence": <sequence_number>,
        "timestamp": <unix_timestamp>,
        "data": {
            "key": <key>,
            "value": <base64_encoded_bytes>,
            "tags": [<tag1>, <tag2>, ...],
            "ttl": <seconds>,
            "db": <database>,
            "namespace": <namespace>,
            ...
        },
        "checksum": <sha256_hex>
    }
    """

    VERSION = "1.0"
    MAX_OPERATION_SIZE = 100 * 1024 * 1024  # 100MB max operation size

    @staticmethod
    def serialize(operation: Operation) -> bytes:
        """
        Serialize an operation to bytes.

        Args:
            operation: Operation to serialize

        Returns:
            Serialized bytes ready for network transmission

        Raises:
            ProtocolError: If serialization fails
        """
        try:
            # Convert operation to dict
            op_dict = operation.to_dict()

            # Encode binary values in data as base64
            if 'value' in op_dict['data'] and isinstance(op_dict['data']['value'], bytes):
                op_dict['data']['value'] = base64.b64encode(op_dict['data']['value']).decode('utf-8')
                op_dict['data']['_value_encoded'] = True

            # Calculate checksum if not present
            if not op_dict['checksum']:
                op_dict['checksum'] = ReplicationProtocol._calculate_checksum(op_dict)

            # Serialize to JSON
            json_str = json.dumps(op_dict, separators=(',', ':'))
            json_bytes = json_str.encode('utf-8')

            # Check size
            if len(json_bytes) > ReplicationProtocol.MAX_OPERATION_SIZE:
                raise ProtocolError(
                    f"Operation size {len(json_bytes)} exceeds maximum {ReplicationProtocol.MAX_OPERATION_SIZE}"
                )

            # Add length prefix (4 bytes, big-endian)
            length = len(json_bytes)
            length_bytes = length.to_bytes(4, byteorder='big')

            return length_bytes + json_bytes

        except Exception as e:
            raise ProtocolError(f"Failed to serialize operation: {e}", operation)

    @staticmethod
    def deserialize(data: bytes) -> Operation:
        """
        Deserialize bytes to an operation.

        Args:
            data: Serialized operation bytes (with length prefix)

        Returns:
            Deserialized Operation object

        Raises:
            ProtocolError: If deserialization or validation fails
        """
        try:
            # Extract length prefix
            if len(data) < 4:
                raise ProtocolError("Data too short for length prefix")

            length = int.from_bytes(data[:4], byteorder='big')

            # Validate length
            if length > ReplicationProtocol.MAX_OPERATION_SIZE:
                raise ProtocolError(f"Operation size {length} exceeds maximum")

            if len(data) < 4 + length:
                raise ProtocolError(f"Data too short: expected {4 + length}, got {len(data)}")

            # Extract JSON
            json_bytes = data[4:4 + length]
            json_str = json_bytes.decode('utf-8')
            op_dict = json.loads(json_str)

            # Decode base64-encoded values
            if '_value_encoded' in op_dict['data'] and op_dict['data']['_value_encoded']:
                op_dict['data']['value'] = base64.b64decode(op_dict['data']['value'])
                del op_dict['data']['_value_encoded']

            # Validate checksum
            received_checksum = op_dict.get('checksum')
            if received_checksum:
                # Temporarily remove checksum for validation
                op_dict_copy = op_dict.copy()
                op_dict_copy['checksum'] = None
                calculated_checksum = ReplicationProtocol._calculate_checksum(op_dict_copy)

                if received_checksum != calculated_checksum:
                    raise ChecksumMismatchError(calculated_checksum, received_checksum)

            # Create Operation object
            operation = Operation.from_dict(op_dict)

            return operation

        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON: {e}")
        except Exception as e:
            if isinstance(e, (ProtocolError, ChecksumMismatchError)):
                raise
            raise ProtocolError(f"Failed to deserialize operation: {e}")

    @staticmethod
    def _calculate_checksum(op_dict: Dict[str, Any]) -> str:
        """
        Calculate SHA256 checksum of operation data.

        Args:
            op_dict: Operation dictionary (without checksum field)

        Returns:
            Hex-encoded SHA256 checksum
        """
        # Create a copy and ensure consistent ordering
        data_for_hash = {
            'type': op_dict['type'],
            'sequence': op_dict['sequence'],
            'timestamp': op_dict['timestamp'],
            'data': op_dict['data']
        }

        # Serialize consistently
        json_str = json.dumps(data_for_hash, sort_keys=True, separators=(',', ':'))

        # Calculate hash
        hasher = hashlib.sha256()
        hasher.update(json_str.encode('utf-8'))

        return hasher.hexdigest()

    @staticmethod
    def create_set_operation(
        sequence: int,
        key: str,
        value: bytes,
        db: str,
        namespace: str,
        tags: Optional[List[str]] = None,
        ttl: Optional[int] = None
    ) -> Operation:
        """
        Create a SET operation.

        Args:
            sequence: Operation sequence number
            key: Key to set
            value: Value to set (bytes)
            db: Database name
            namespace: Namespace
            tags: Optional tags
            ttl: Optional TTL in seconds

        Returns:
            SET Operation
        """
        data = {
            'key': key,
            'value': value,
            'db': db,
            'namespace': namespace
        }

        if tags:
            data['tags'] = tags
        if ttl is not None:
            data['ttl'] = ttl

        operation = Operation(
            type=OperationType.SET,
            sequence=sequence,
            timestamp=time.time(),
            data=data
        )

        # Calculate checksum
        op_dict = operation.to_dict()
        if isinstance(op_dict['data'].get('value'), bytes):
            op_dict['data']['value'] = base64.b64encode(op_dict['data']['value']).decode('utf-8')
            op_dict['data']['_value_encoded'] = True
        op_dict['checksum'] = None
        operation.checksum = ReplicationProtocol._calculate_checksum(op_dict)

        return operation

    @staticmethod
    def create_delete_operation(
        sequence: int,
        key: str,
        db: str,
        namespace: str
    ) -> Operation:
        """
        Create a DELETE operation.

        Args:
            sequence: Operation sequence number
            key: Key to delete
            db: Database name
            namespace: Namespace

        Returns:
            DELETE Operation
        """
        data = {
            'key': key,
            'db': db,
            'namespace': namespace
        }

        operation = Operation(
            type=OperationType.DELETE,
            sequence=sequence,
            timestamp=time.time(),
            data=data
        )

        # Calculate checksum
        op_dict = operation.to_dict()
        op_dict['checksum'] = None
        operation.checksum = ReplicationProtocol._calculate_checksum(op_dict)

        return operation

    @staticmethod
    def create_heartbeat_operation(sequence: int) -> Operation:
        """
        Create a HEARTBEAT operation.

        Args:
            sequence: Operation sequence number

        Returns:
            HEARTBEAT Operation
        """
        operation = Operation(
            type=OperationType.HEARTBEAT,
            sequence=sequence,
            timestamp=time.time(),
            data={}
        )

        # Calculate checksum
        op_dict = operation.to_dict()
        op_dict['checksum'] = None
        operation.checksum = ReplicationProtocol._calculate_checksum(op_dict)

        return operation

    @staticmethod
    def create_sync_request(sequence: int, from_sequence: int) -> Operation:
        """
        Create a SYNC_REQUEST operation.

        Args:
            sequence: Operation sequence number
            from_sequence: Sequence to sync from

        Returns:
            SYNC_REQUEST Operation
        """
        operation = Operation(
            type=OperationType.SYNC_REQUEST,
            sequence=sequence,
            timestamp=time.time(),
            data={'from_sequence': from_sequence}
        )

        # Calculate checksum
        op_dict = operation.to_dict()
        op_dict['checksum'] = None
        operation.checksum = ReplicationProtocol._calculate_checksum(op_dict)

        return operation

    @staticmethod
    def validate_operation(operation: Operation) -> bool:
        """
        Validate an operation's structure and checksum.

        Args:
            operation: Operation to validate

        Returns:
            True if valid

        Raises:
            ProtocolError: If validation fails
        """
        # Check required fields
        if not isinstance(operation.sequence, int):
            raise ProtocolError("Invalid sequence number")

        if not isinstance(operation.timestamp, (int, float)):
            raise ProtocolError("Invalid timestamp")

        if not isinstance(operation.data, dict):
            raise ProtocolError("Invalid data field")

        # Validate checksum if present
        if operation.checksum:
            op_dict = operation.to_dict()
            op_dict['checksum'] = None

            # Handle binary values
            if 'value' in op_dict['data'] and isinstance(op_dict['data']['value'], bytes):
                op_dict['data']['value'] = base64.b64encode(op_dict['data']['value']).decode('utf-8')
                op_dict['data']['_value_encoded'] = True

            calculated = ReplicationProtocol._calculate_checksum(op_dict)
            if operation.checksum != calculated:
                raise ChecksumMismatchError(calculated, operation.checksum)

        return True
