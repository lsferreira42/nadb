"""
Transaction system for NADB with rollback support and batch operations.
"""
import threading
import time
import uuid
from typing import Dict, List, Tuple, Any, Optional, Union
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import logging

from logging_config import LoggingConfig


class TransactionState(Enum):
    """Transaction states."""
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class Operation:
    """Represents a single operation in a transaction."""
    op_type: str  # 'set', 'delete', 'set_with_ttl'
    key: str
    value: Optional[bytes] = None
    tags: Optional[List[str]] = None
    ttl: Optional[int] = None
    original_value: Optional[bytes] = None  # For rollback
    original_existed: bool = False  # For rollback


@dataclass
class Transaction:
    """Represents a transaction with operations and state."""
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: TransactionState = TransactionState.ACTIVE
    operations: List[Operation] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    committed_at: Optional[float] = None
    rolled_back_at: Optional[float] = None
    isolation_level: str = "READ_COMMITTED"
    
    def add_operation(self, op_type: str, key: str, value: Optional[bytes] = None, 
                     tags: Optional[List[str]] = None, ttl: Optional[int] = None):
        """Add an operation to the transaction."""
        if self.state != TransactionState.ACTIVE:
            raise RuntimeError(f"Cannot add operations to {self.state.value} transaction")
        
        operation = Operation(
            op_type=op_type,
            key=key,
            value=value,
            tags=tags,
            ttl=ttl
        )
        self.operations.append(operation)
        return operation


class TransactionManager:
    """Manages transactions for KeyValueStore."""
    
    def __init__(self, kv_store):
        self.kv_store = kv_store
        self.active_transactions: Dict[str, Transaction] = {}
        self.lock = threading.RLock()
        self.logger = LoggingConfig.get_logger('transaction')
        self.perf_logger = LoggingConfig.get_performance_logger('transaction')
    
    def begin_transaction(self, isolation_level: str = "READ_COMMITTED") -> Transaction:
        """Begin a new transaction."""
        transaction = Transaction(isolation_level=isolation_level)
        
        with self.lock:
            self.active_transactions[transaction.transaction_id] = transaction
        
        self.logger.info(f"Transaction {transaction.transaction_id} started", 
                        extra={'transaction_id': transaction.transaction_id})
        return transaction
    
    def commit_transaction(self, transaction: Transaction) -> bool:
        """Commit a transaction."""
        if transaction.state != TransactionState.ACTIVE:
            raise RuntimeError(f"Cannot commit {transaction.state.value} transaction")
        
        op_id = f"commit_{transaction.transaction_id}"
        self.perf_logger.start_operation(op_id, "commit_transaction", 
                                       transaction_id=transaction.transaction_id,
                                       operation_count=len(transaction.operations))
        
        try:
            # Execute all operations
            for operation in transaction.operations:
                self._execute_operation(operation)
            
            # Mark as committed
            transaction.state = TransactionState.COMMITTED
            transaction.committed_at = time.time()
            
            # Remove from active transactions
            with self.lock:
                self.active_transactions.pop(transaction.transaction_id, None)
            
            self.perf_logger.end_operation(op_id, success=True)
            self.logger.info(f"Transaction {transaction.transaction_id} committed successfully")
            return True
            
        except Exception as e:
            # Rollback on failure
            self.logger.error(f"Transaction {transaction.transaction_id} failed: {e}")
            self._rollback_transaction(transaction)
            self.perf_logger.end_operation(op_id, success=False, error=str(e))
            raise
    
    def rollback_transaction(self, transaction: Transaction) -> bool:
        """Manually rollback a transaction."""
        return self._rollback_transaction(transaction)
    
    def _rollback_transaction(self, transaction: Transaction) -> bool:
        """Internal rollback implementation."""
        if transaction.state not in [TransactionState.ACTIVE, TransactionState.FAILED]:
            self.logger.warning(f"Cannot rollback {transaction.state.value} transaction")
            return False
        
        op_id = f"rollback_{transaction.transaction_id}"
        self.perf_logger.start_operation(op_id, "rollback_transaction",
                                       transaction_id=transaction.transaction_id,
                                       operation_count=len(transaction.operations))
        
        try:
            # Reverse operations in reverse order
            for operation in reversed(transaction.operations):
                self._reverse_operation(operation)
            
            transaction.state = TransactionState.ROLLED_BACK
            transaction.rolled_back_at = time.time()
            
            # Remove from active transactions
            with self.lock:
                self.active_transactions.pop(transaction.transaction_id, None)
            
            self.perf_logger.end_operation(op_id, success=True)
            self.logger.info(f"Transaction {transaction.transaction_id} rolled back successfully")
            return True
            
        except Exception as e:
            transaction.state = TransactionState.FAILED
            self.logger.error(f"Failed to rollback transaction {transaction.transaction_id}: {e}")
            self.perf_logger.end_operation(op_id, success=False, error=str(e))
            return False
    
    def _store_original_values(self, transaction: Transaction):
        """Store original values for rollback purposes."""
        for operation in transaction.operations:
            try:
                # Check if key exists and store original value
                original_value = self.kv_store.get(operation.key)
                operation.original_value = original_value
                operation.original_existed = True
            except KeyError:
                operation.original_existed = False
    
    def _execute_operation(self, operation: Operation):
        """Execute a single operation."""
        if operation.op_type == 'set':
            self.kv_store.set(operation.key, operation.value, operation.tags)
        elif operation.op_type == 'set_with_ttl':
            self.kv_store.set_with_ttl(operation.key, operation.value, 
                                     operation.ttl, operation.tags)
        elif operation.op_type == 'delete':
            self.kv_store.delete(operation.key)
        else:
            raise ValueError(f"Unknown operation type: {operation.op_type}")
    
    def _reverse_operation(self, operation: Operation):
        """Reverse a single operation for rollback."""
        try:
            if operation.op_type in ['set', 'set_with_ttl']:
                if operation.original_existed:
                    # Restore original value
                    self.kv_store.set(operation.key, operation.original_value)
                else:
                    # Delete the key that was created
                    self.kv_store.delete(operation.key)
            elif operation.op_type == 'delete':
                if operation.original_existed:
                    # Restore the deleted key
                    self.kv_store.set(operation.key, operation.original_value)
        except Exception as e:
            self.logger.error(f"Failed to reverse operation {operation.op_type} for key {operation.key}: {e}")
            # Continue with other operations
    
    @contextmanager
    def transaction(self, isolation_level: str = "READ_COMMITTED"):
        """Context manager for transactions."""
        transaction = self.begin_transaction(isolation_level)
        try:
            yield TransactionContext(self, transaction)
            self.commit_transaction(transaction)
        except Exception as e:
            self.logger.error(f"Transaction failed: {e}")
            self._rollback_transaction(transaction)
            raise
    
    def get_active_transactions(self) -> List[Transaction]:
        """Get list of active transactions."""
        with self.lock:
            return list(self.active_transactions.values())
    
    def cleanup_stale_transactions(self, max_age_seconds: int = 3600):
        """Clean up transactions that have been active too long."""
        current_time = time.time()
        stale_transactions = []
        
        with self.lock:
            for transaction in list(self.active_transactions.values()):
                if current_time - transaction.created_at > max_age_seconds:
                    stale_transactions.append(transaction)
        
        for transaction in stale_transactions:
            self.logger.warning(f"Cleaning up stale transaction {transaction.transaction_id}")
            self._rollback_transaction(transaction)


class TransactionContext:
    """Context for operations within a transaction."""
    
    def __init__(self, manager: TransactionManager, transaction: Transaction):
        self.manager = manager
        self.transaction = transaction
        self.kv_store = manager.kv_store
    
    def set(self, key: str, value: bytes, tags: Optional[List[str]] = None):
        """Add a set operation to the transaction."""
        operation = self.transaction.add_operation('set', key, value, tags)
        self._store_original_value(operation)
    
    def set_with_ttl(self, key: str, value: bytes, ttl_seconds: int, 
                     tags: Optional[List[str]] = None):
        """Add a set_with_ttl operation to the transaction."""
        operation = self.transaction.add_operation('set_with_ttl', key, value, tags, ttl_seconds)
        self._store_original_value(operation)
    
    def delete(self, key: str):
        """Add a delete operation to the transaction."""
        operation = self.transaction.add_operation('delete', key)
        self._store_original_value(operation)
    
    def batch_set(self, items: List[Tuple[str, bytes, Optional[List[str]]]]):
        """Add multiple set operations to the transaction."""
        for key, value, tags in items:
            self.set(key, value, tags)
    
    def batch_delete(self, keys: List[str]):
        """Add multiple delete operations to the transaction."""
        for key in keys:
            self.delete(key)
    
    def get_operation_count(self) -> int:
        """Get the number of operations in this transaction."""
        return len(self.transaction.operations)
    
    def _store_original_value(self, operation: Operation):
        """Store original value for rollback purposes."""
        try:
            # Check if key exists and store original value
            original_value = self.kv_store.get(operation.key)
            operation.original_value = original_value
            operation.original_existed = True
        except KeyError:
            operation.original_existed = False