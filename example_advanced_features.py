#!/usr/bin/env python3
"""
Example demonstrating the advanced features of NADB:
1. Connection pooling for Redis
2. Structured logging
3. Transactions with rollback
4. Backup and recovery
5. Advanced indexing and caching
"""
import tempfile
import time
import json
from datetime import datetime

from nakv import KeyValueStore, KeyValueSync
from logging_config import LoggingConfig


def main():
    print("=== NADB Advanced Features Demo ===\n")
    
    # Setup logging
    LoggingConfig.setup_logging()
    logger = LoggingConfig.get_logger('demo')
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as data_dir:
        # Create sync manager
        sync_manager = KeyValueSync(flush_interval_seconds=2)
        sync_manager.start()
        
        try:
            # Create KeyValueStore with all advanced features enabled
            kv_store = KeyValueStore(
                data_folder_path=data_dir,
                db="demo_db",
                buffer_size_mb=1,
                namespace="advanced_demo",
                sync=sync_manager,
                compression_enabled=True,
                storage_backend="fs",  # Change to "redis" if Redis is available
                enable_transactions=True,
                enable_backup=True,
                enable_indexing=True,
                cache_size=1000
            )
            
            logger.info("KeyValueStore created with advanced features")
            
            # 1. Demonstrate Transactions
            print("1. Testing Transactions...")
            demo_transactions(kv_store)
            
            # 2. Demonstrate Advanced Indexing and Caching
            print("\n2. Testing Advanced Indexing and Caching...")
            demo_indexing(kv_store)
            
            # 3. Demonstrate Backup and Recovery
            print("\n3. Testing Backup and Recovery...")
            demo_backup(kv_store)
            
            # 4. Show Performance Statistics
            print("\n4. Performance Statistics...")
            demo_statistics(kv_store)
            
            # Close the store
            kv_store.close()
            
        finally:
            sync_manager.sync_exit()


def demo_transactions(kv_store):
    """Demonstrate transaction functionality."""
    print("  Creating transaction with multiple operations...")
    
    # Test successful transaction
    with kv_store.transaction() as tx:
        tx.set("user:1", b"Alice", ["user", "active"])
        tx.set("user:2", b"Bob", ["user", "inactive"])
        tx.set("config:theme", b"dark", ["config"])
    
    print("  ✓ Transaction committed successfully")
    
    # Verify data exists
    assert kv_store.get("user:1") == b"Alice"
    assert kv_store.get("user:2") == b"Bob"
    
    # Test transaction rollback
    try:
        with kv_store.transaction() as tx:
            tx.set("user:3", b"Charlie", ["user", "active"])
            tx.set("user:4", b"David", ["user", "active"])
            # Simulate an error
            raise ValueError("Simulated error")
    except ValueError:
        print("  ✓ Transaction rolled back due to error")
    
    # Verify rollback worked
    try:
        kv_store.get("user:3")
        assert False, "Key should not exist after rollback"
    except KeyError:
        print("  ✓ Rollback verified - keys don't exist")


def demo_indexing(kv_store):
    """Demonstrate advanced indexing and caching."""
    print("  Adding test data with various tags...")
    
    # Add test data
    test_data = [
        ("product:1", b"Laptop", ["electronics", "computer", "expensive"]),
        ("product:2", b"Mouse", ["electronics", "computer", "cheap"]),
        ("product:3", b"Book", ["media", "education", "cheap"]),
        ("product:4", b"Phone", ["electronics", "mobile", "expensive"]),
        ("product:5", b"Tablet", ["electronics", "mobile", "expensive"]),
    ]
    
    for key, value, tags in test_data:
        kv_store.set(key, value, tags)
    
    # Test advanced tag queries with pagination
    print("  Testing advanced tag queries...")
    
    # Query with AND operator
    result = kv_store.query_by_tags_advanced(["electronics", "expensive"], "AND", page=1, page_size=2)
    print(f"  Electronics AND expensive (page 1): {len(result['keys'])} results")
    print(f"  Total: {result['total_count']}, Has more: {result['has_more']}")
    
    # Query with OR operator
    result = kv_store.query_by_tags_advanced(["mobile", "education"], "OR")
    print(f"  Mobile OR education: {len(result['keys'])} results")
    
    # Test complex queries (if indexing is enabled)
    try:
        conditions = [
            {"field": "tags", "operator": "or", "values": ["electronics", "media"]},
            {"field": "tags", "operator": "and", "value": ["cheap"]}
        ]
        result = kv_store.complex_query(conditions)
        print(f"  Complex query: {len(result['keys'])} results")
    except RuntimeError:
        print("  Complex queries not available (indexing disabled)")
    
    # Show cache statistics
    stats = kv_store.get_stats()
    if 'cache_stats' in stats:
        cache_stats = stats['cache_stats']
        print(f"  Query cache hit rate: {cache_stats['query_cache']['hit_rate']:.2%}")


def demo_backup(kv_store):
    """Demonstrate backup and recovery functionality."""
    print("  Creating full backup...")
    
    try:
        # Create a full backup
        backup_meta = kv_store.create_backup("demo_backup_full", compression=True)
        print(f"  ✓ Full backup created: {backup_meta.backup_id}")
        print(f"    Files: {backup_meta.file_count}, Size: {backup_meta.total_size} bytes")
        
        # Add more data
        kv_store.set("new_key", b"new_value", ["new"])
        
        # Create incremental backup
        inc_backup_meta = kv_store.create_incremental_backup(
            "demo_backup_full", "demo_backup_inc", compression=True
        )
        print(f"  ✓ Incremental backup created: {inc_backup_meta.backup_id}")
        
        # List all backups
        backups = kv_store.list_backups()
        print(f"  Available backups: {len(backups)}")
        for backup in backups:
            print(f"    - {backup.backup_id} ({backup.backup_type})")
        
        # Verify backup integrity
        is_valid = kv_store.verify_backup("demo_backup_full")
        print(f"  ✓ Backup integrity check: {'PASSED' if is_valid else 'FAILED'}")
        
    except RuntimeError as e:
        print(f"  Backup not available: {e}")


def demo_statistics(kv_store):
    """Show performance and usage statistics."""
    stats = kv_store.get_stats()
    
    print("  Store Statistics:")
    print(f"    Database: {stats['db']}")
    print(f"    Namespace: {stats['namespace']}")
    print(f"    Total keys: {stats['count']}")
    print(f"    Storage backend: {stats['storage_backend']}")
    
    if 'performance' in stats:
        perf = stats['performance']
        print(f"    Uptime: {perf['uptime_seconds']:.1f}s")
        print(f"    Bytes read: {perf['bytes_read']}")
        print(f"    Bytes written: {perf['bytes_written']}")
        
        if 'operations' in perf:
            print("    Operations:")
            for op_name, op_stats in perf['operations'].items():
                print(f"      {op_name}: {op_stats['count']} ops, avg {op_stats['avg_ms']:.2f}ms")
    
    if 'index_stats' in stats:
        print("    Index Statistics:")
        for index_name, index_stats in stats['index_stats'].items():
            print(f"      {index_name}: {index_stats.unique_values} unique values")
    
    if 'cache_stats' in stats:
        print("    Cache Statistics:")
        for cache_name, cache_stats in stats['cache_stats'].items():
            print(f"      {cache_name}: {cache_stats['hit_rate']:.2%} hit rate")
    
    if 'active_transactions' in stats:
        print(f"    Active transactions: {stats['active_transactions']}")


if __name__ == "__main__":
    main()