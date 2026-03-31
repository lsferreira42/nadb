#!/usr/bin/env python3
"""
Comprehensive tests for NADB advanced features:
- Transactions
- Backup & Recovery  
- Indexing & Caching
- Structured Logging
- Connection Pooling
"""
import pytest
import tempfile
import time
import threading
from datetime import datetime

from nakv import KeyValueStore, KeyValueSync
from logging_config import LoggingConfig
from transaction import TransactionManager
from backup_manager import BackupManager
from index_manager import IndexManager


@pytest.fixture
def kv_sync():
    sync = KeyValueSync(flush_interval_seconds=1)
    sync.start()
    yield sync
    sync.sync_exit()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


@pytest.fixture
def advanced_kv_store(kv_sync, temp_dir):
    """KeyValueStore with all advanced features enabled."""
    store = KeyValueStore(
        data_folder_path=temp_dir,
        db="advanced_test",
        buffer_size_mb=1,
        namespace="test",
        sync=kv_sync,
        compression_enabled=True,
        storage_backend="fs",
        enable_transactions=True,
        enable_backup=True,
        enable_indexing=True,
        cache_size=1000
    )
    yield store
    store.close()


class TestTransactions:
    """Test transaction functionality."""
    
    def test_successful_transaction(self, advanced_kv_store):
        """Test successful transaction commit."""
        with advanced_kv_store.transaction() as tx:
            tx.set("tx_key1", b"value1", ["transaction", "test"])
            tx.set("tx_key2", b"value2", ["transaction", "test"])
            tx.set("tx_key3", b"value3", ["transaction", "test"])
        
        # Verify all data was committed
        assert advanced_kv_store.get("tx_key1") == b"value1"
        assert advanced_kv_store.get("tx_key2") == b"value2"
        assert advanced_kv_store.get("tx_key3") == b"value3"
    
    def test_transaction_rollback(self, advanced_kv_store):
        """Test transaction rollback on error."""
        # Store initial data
        advanced_kv_store.set("existing_key", b"existing_value")
        
        try:
            with advanced_kv_store.transaction() as tx:
                tx.set("rollback_key1", b"value1", ["rollback", "test"])
                tx.set("rollback_key2", b"value2", ["rollback", "test"])
                tx.set("existing_key", b"modified_value")  # Modify existing key
                raise ValueError("Simulated transaction error")
        except ValueError:
            pass
        
        # Verify rollback worked
        with pytest.raises(KeyError):
            advanced_kv_store.get("rollback_key1")
        with pytest.raises(KeyError):
            advanced_kv_store.get("rollback_key2")
        
        # Verify existing key was restored
        assert advanced_kv_store.get("existing_key") == b"existing_value"
    
    def test_batch_operations(self, advanced_kv_store):
        """Test batch operations in transactions."""
        batch_data = [
            ("batch_key1", b"batch_value1", ["batch", "test"]),
            ("batch_key2", b"batch_value2", ["batch", "test"]),
            ("batch_key3", b"batch_value3", ["batch", "test"])
        ]
        
        with advanced_kv_store.transaction() as tx:
            tx.batch_set(batch_data)
        
        # Verify all batch data was committed
        for key, expected_value, _ in batch_data:
            assert advanced_kv_store.get(key) == expected_value
        
        # Test batch delete
        keys_to_delete = [key for key, _, _ in batch_data]
        with advanced_kv_store.transaction() as tx:
            tx.batch_delete(keys_to_delete)
        
        # Verify all keys were deleted
        for key in keys_to_delete:
            with pytest.raises(KeyError):
                advanced_kv_store.get(key)
    
    def test_transaction_isolation(self, advanced_kv_store):
        """Test transaction isolation levels."""
        # Test with different isolation levels
        tx1 = advanced_kv_store.begin_transaction("READ_COMMITTED")
        
        # Verify transaction was created
        assert tx1.state.value == "active"
        assert tx1.isolation_level == "READ_COMMITTED"
        
        # Commit empty transaction
        advanced_kv_store.commit_transaction(tx1)
        assert tx1.state.value == "committed"


class TestBackupRecovery:
    """Test backup and recovery functionality."""
    
    def test_full_backup_creation(self, advanced_kv_store):
        """Test creating a full backup."""
        # Add test data
        test_data = {
            "backup_test1": (b"data1", ["backup", "test", "important"]),
            "backup_test2": (b"data2", ["backup", "test", "normal"]),
            "backup_test3": (b"data3", ["backup", "test", "archive"])
        }
        
        for key, (value, tags) in test_data.items():
            advanced_kv_store.set(key, value, tags)
        
        advanced_kv_store.flush()
        
        # Create backup
        backup_meta = advanced_kv_store.create_backup("test_full_backup", compression=True)
        
        # Verify backup metadata
        assert backup_meta.backup_id == "test_full_backup"
        assert backup_meta.backup_type == "full"
        assert backup_meta.file_count == len(test_data)
        assert backup_meta.compression == True
        assert backup_meta.total_size > 0
        assert backup_meta.checksum is not None
    
    def test_incremental_backup(self, advanced_kv_store):
        """Test incremental backup creation."""
        # Create initial data and full backup
        for i in range(3):
            advanced_kv_store.set(f"initial_key_{i}", f"initial_value_{i}".encode(), ["initial"])
        
        advanced_kv_store.flush()
        full_backup = advanced_kv_store.create_backup("full_backup_for_inc")
        
        # Add more data after full backup
        for i in range(2):
            advanced_kv_store.set(f"incremental_key_{i}", f"incremental_value_{i}".encode(), ["incremental"])
        
        advanced_kv_store.flush()
        
        # Create incremental backup
        inc_backup = advanced_kv_store.create_incremental_backup(
            full_backup.backup_id, "incremental_backup"
        )
        
        # Verify incremental backup
        assert inc_backup.backup_type == "incremental"
        assert inc_backup.parent_backup_id == full_backup.backup_id
        assert inc_backup.file_count == 2  # Only new files
    
    def test_backup_verification(self, advanced_kv_store):
        """Test backup integrity verification."""
        # Create test data and backup
        advanced_kv_store.set("verify_key", b"verify_data", ["verify"])
        advanced_kv_store.flush()
        
        backup_meta = advanced_kv_store.create_backup("verification_test")
        
        # Verify backup integrity
        is_valid = advanced_kv_store.verify_backup(backup_meta.backup_id)
        assert is_valid == True
        
        # Test verification of non-existent backup
        is_valid = advanced_kv_store.verify_backup("non_existent_backup")
        assert is_valid == False
    
    def test_backup_restore(self, advanced_kv_store):
        """Test restoring from backup."""
        # Create original data
        original_data = {
            "restore_key1": b"restore_value1",
            "restore_key2": b"restore_value2",
            "restore_key3": b"restore_value3"
        }
        
        for key, value in original_data.items():
            advanced_kv_store.set(key, value, ["restore", "test"])
        
        advanced_kv_store.flush()
        
        # Create backup
        backup_meta = advanced_kv_store.create_backup("restore_test_backup")
        
        # Modify/delete original data
        advanced_kv_store.delete("restore_key1")
        advanced_kv_store.set("restore_key2", b"modified_value", ["modified"])
        advanced_kv_store.set("new_key", b"new_value", ["new"])
        
        # Restore from backup (without clearing existing data)
        success = advanced_kv_store.restore_backup(
            backup_meta.backup_id, 
            verify_integrity=True, 
            clear_existing=False
        )
        assert success == True
        
        # Verify restoration
        assert advanced_kv_store.get("restore_key1") == b"restore_value1"  # Restored
        assert advanced_kv_store.get("restore_key2") == b"restore_value2"  # Restored original
        assert advanced_kv_store.get("restore_key3") == b"restore_value3"  # Unchanged
        assert advanced_kv_store.get("new_key") == b"new_value"  # Still exists
    
    def test_backup_list_and_cleanup(self, advanced_kv_store):
        """Test listing and cleaning up backups."""
        # Create multiple backups
        backup_ids = []
        for i in range(3):
            advanced_kv_store.set(f"cleanup_key_{i}", f"cleanup_value_{i}".encode())
            advanced_kv_store.flush()
            backup_meta = advanced_kv_store.create_backup(f"cleanup_backup_{i}")
            backup_ids.append(backup_meta.backup_id)
        
        # List backups
        backups = advanced_kv_store.list_backups()
        assert len(backups) >= 3
        
        # Verify all our backups are in the list
        backup_ids_in_list = [b.backup_id for b in backups]
        for backup_id in backup_ids:
            assert backup_id in backup_ids_in_list


class TestIndexingCaching:
    """Test indexing and caching functionality."""
    
    def test_tag_indexing(self, advanced_kv_store):
        """Test tag-based indexing."""
        # Add test data with various tag combinations
        test_items = [
            ("item1", b"data1", ["category:electronics", "price:high", "brand:apple"]),
            ("item2", b"data2", ["category:electronics", "price:low", "brand:samsung"]),
            ("item3", b"data3", ["category:books", "price:low", "genre:fiction"]),
            ("item4", b"data4", ["category:electronics", "price:high", "brand:apple"]),
            ("item5", b"data5", ["category:books", "price:high", "genre:technical"])
        ]
        
        for key, value, tags in test_items:
            advanced_kv_store.set(key, value, tags)
        
        advanced_kv_store.flush()
        
        # Test basic tag queries
        electronics = advanced_kv_store.query_by_tags(["category:electronics"])
        assert len(electronics) == 3
        
        # Test multiple tag queries (AND)
        expensive_electronics = advanced_kv_store.query_by_tags(["category:electronics", "price:high"])
        assert len(expensive_electronics) == 2
        
        # Test advanced queries with pagination
        result = advanced_kv_store.query_by_tags_advanced(
            ["category:electronics"], "AND", page=1, page_size=2
        )
        assert len(result.keys) == 2
        assert result.total_count == 3
        assert result.has_more == True
        
        # Test OR queries
        result = advanced_kv_store.query_by_tags_advanced(
            ["brand:apple", "genre:fiction"], "OR"
        )
        assert len(result.keys) == 3  # 2 apple items + 1 fiction book
    
    def test_complex_queries(self, advanced_kv_store):
        """Test complex multi-condition queries."""
        # Add test data
        products = [
            ("prod1", b"Laptop", ["electronics", "computer", "expensive", "portable"]),
            ("prod2", b"Desktop", ["electronics", "computer", "expensive", "stationary"]),
            ("prod3", b"Mouse", ["electronics", "accessory", "cheap", "portable"]),
            ("prod4", b"Book", ["media", "education", "cheap", "portable"]),
            ("prod5", b"Monitor", ["electronics", "display", "expensive", "stationary"])
        ]
        
        for key, value, tags in products:
            advanced_kv_store.set(key, value, tags)
        
        advanced_kv_store.flush()
        
        # Complex query: (electronics OR media) AND cheap
        conditions = [
            {"field": "tags", "operator": "or", "values": ["electronics", "media"]},
            {"field": "tags", "operator": "and", "values": ["cheap"]}
        ]
        
        result = advanced_kv_store.complex_query(conditions)
        assert len(result.keys) == 2  # mouse and book
        assert "prod3" in result.keys  # mouse
        assert "prod4" in result.keys  # book
    
    def test_query_caching(self, advanced_kv_store):
        """Test query result caching."""
        # Add test data
        for i in range(10):
            advanced_kv_store.set(f"cache_test_{i}", f"data_{i}".encode(), ["cache", "test"])
        
        advanced_kv_store.flush()
        
        # First query - should be a cache miss
        result1 = advanced_kv_store.query_by_tags_advanced(["cache", "test"])
        assert result1.cache_hit == False
        
        # Second identical query - should be a cache hit
        result2 = advanced_kv_store.query_by_tags_advanced(["cache", "test"])
        assert result2.cache_hit == True
        
        # Results should be identical
        assert result1.keys == result2.keys
        assert result1.total_count == result2.total_count
    
    def test_index_optimization(self, advanced_kv_store):
        """Test index optimization and statistics."""
        # Add data and perform queries to generate usage statistics
        for i in range(20):
            tags = ["test", f"category_{i % 3}", f"priority_{i % 2}"]
            advanced_kv_store.set(f"opt_key_{i}", f"data_{i}".encode(), tags)
        
        advanced_kv_store.flush()
        
        # Perform various queries to generate statistics
        advanced_kv_store.query_by_tags(["test"])
        advanced_kv_store.query_by_tags(["category_0"])
        advanced_kv_store.query_by_tags(["priority_1"])
        
        # Get statistics
        stats = advanced_kv_store.get_stats()
        
        if 'index_stats' in stats:
            assert 'tag_index' in stats['index_stats']
            tag_index_stats = stats['index_stats']['tag_index']
            assert tag_index_stats.unique_values > 0
            assert tag_index_stats.total_entries > 0
        
        if 'cache_stats' in stats:
            assert 'query_cache' in stats['cache_stats']
        
        # Test optimization
        advanced_kv_store.optimize_indexes()
        
        # Test index rebuild
        advanced_kv_store.rebuild_indexes()
        
        # Verify data is still accessible after rebuild
        assert advanced_kv_store.get("opt_key_0") == b"data_0"


class TestStructuredLogging:
    """Test structured logging functionality."""
    
    def test_logging_configuration(self):
        """Test logging configuration and setup."""
        # Test getting different types of loggers
        app_logger = LoggingConfig.get_logger('application')
        storage_logger = LoggingConfig.get_logger('storage')
        perf_logger = LoggingConfig.get_performance_logger('test')
        
        assert app_logger is not None
        assert storage_logger is not None
        assert perf_logger is not None
        
        # Test logging with structured data
        app_logger.info("Test message", extra={
            'user_id': 'test_user',
            'operation': 'test_operation',
            'success': True
        })
    
    def test_performance_logging(self):
        """Test performance logging and metrics."""
        perf_logger = LoggingConfig.get_performance_logger('test')
        
        # Test operation tracking
        op_id = "test_operation_123"
        perf_logger.start_operation(op_id, "test_op", key="test_key", size=1024)
        
        # Simulate some work
        time.sleep(0.01)
        
        perf_logger.end_operation(op_id, success=True, result_count=1)
        
        # Test metric logging
        perf_logger.log_metric("test_metric", 42.5, unit="ms", component="test")
    
    def test_logging_integration(self, advanced_kv_store):
        """Test logging integration with KeyValueStore operations."""
        # Perform operations that should generate logs
        advanced_kv_store.set("log_test_key", b"log_test_value", ["logging", "test"])
        advanced_kv_store.get("log_test_key")
        advanced_kv_store.delete("log_test_key")
        
        # Get stats which should include performance metrics
        stats = advanced_kv_store.get_stats()
        assert 'performance' in stats
        
        if 'operations' in stats['performance']:
            # Verify that operations were logged
            operations = stats['performance']['operations']
            assert len(operations) > 0


class TestConcurrency:
    """Test concurrent operations and thread safety."""
    
    def test_concurrent_transactions(self, advanced_kv_store):
        """Test concurrent transaction handling."""
        results = []
        errors = []
        
        def transaction_worker(worker_id):
            try:
                with advanced_kv_store.transaction() as tx:
                    for i in range(5):
                        key = f"concurrent_tx_{worker_id}_{i}"
                        value = f"value_{worker_id}_{i}".encode()
                        tx.set(key, value, ["concurrent", "transaction"])
                results.append(f"Worker {worker_id} completed")
            except Exception as e:
                errors.append(f"Worker {worker_id} error: {e}")
        
        # Create multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=transaction_worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join(timeout=10)
        
        # Verify results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 3, f"Not all workers completed: {results}"
        
        # Verify all data was committed
        for worker_id in range(3):
            for i in range(5):
                key = f"concurrent_tx_{worker_id}_{i}"
                expected_value = f"value_{worker_id}_{i}".encode()
                assert advanced_kv_store.get(key) == expected_value
    
    def test_concurrent_queries(self, advanced_kv_store):
        """Test concurrent query operations."""
        # Add test data
        for i in range(50):
            advanced_kv_store.set(f"query_test_{i}", f"data_{i}".encode(), 
                                ["concurrent", "query", f"batch_{i // 10}"])
        
        advanced_kv_store.flush()
        
        query_results = []
        query_errors = []
        
        def query_worker(worker_id):
            try:
                # Perform various queries
                result1 = advanced_kv_store.query_by_tags(["concurrent"])
                result2 = advanced_kv_store.query_by_tags_advanced(["query"], "AND", page=1, page_size=10)
                result3 = advanced_kv_store.query_by_tags([f"batch_{worker_id % 5}"])
                
                query_results.append({
                    'worker_id': worker_id,
                    'result1_count': len(result1),
                    'result2_count': len(result2.keys),
                    'result3_count': len(result3)
                })
            except Exception as e:
                query_errors.append(f"Query worker {worker_id} error: {e}")
        
        # Create multiple query threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=query_worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join(timeout=10)
        
        # Verify results
        assert len(query_errors) == 0, f"Query errors occurred: {query_errors}"
        assert len(query_results) == 5, f"Not all query workers completed: {query_results}"
        
        # Verify query results are consistent
        for result in query_results:
            assert result['result1_count'] == 50  # All items have 'concurrent' tag
            assert result['result2_count'] == 10  # Page size limit


if __name__ == "__main__":
    pytest.main([__file__, "-v"])