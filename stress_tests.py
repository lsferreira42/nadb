#!/usr/bin/env python3
"""
Stress test for NADB Key-Value Store.

This script creates 100,000 files for each backend (filesystem and Redis),
uses various features like tags and TTLs, performs reads and queries,
then cleans up and reports performance statistics.
"""
import os
import time
import random
import string
import json
import statistics
import argparse
import concurrent.futures
import threading
from datetime import datetime

from nakv import KeyValueStore, KeyValueSync
from storage_backends import StorageFactory

# Parse command line arguments
def parse_args():
    parser = argparse.ArgumentParser(description='NADB Key-Value Store Stress Test')
    
    # Test configuration
    parser.add_argument('--num-files', type=int, default=1000, help='Number of files to create')
    parser.add_argument('--num-reads', type=int, default=1_000, help='Number of files to read')
    parser.add_argument('--num-queries', type=int, default=100, help='Number of tag queries to perform')
    parser.add_argument('--min-size', type=int, default=100, help='Minimum file size in bytes')
    parser.add_argument('--max-size', type=int, default=10000, help='Maximum file size in bytes')
    parser.add_argument('--tags-per-file', type=int, default=3, help='Maximum number of tags per file')
    parser.add_argument('--threads', type=int, default=None, help='Number of threads to use (defaults to CPU count)')
    
    # Backends to test
    parser.add_argument('--backends', type=str, default='fs,redis', 
                        help='Comma-separated list of backends to test (fs,redis)')
    
    # Redis configuration
    parser.add_argument('--redis-host', type=str, default='localhost', help='Redis host')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis port')
    parser.add_argument('--redis-db', type=int, default=0, help='Redis database number')
    parser.add_argument('--redis-password', type=str, default=None, help='Redis password')
    
    args = parser.parse_args()
    return args

# Configuration (will be overridden by command line args)
NUM_FILES = 1000
NUM_READS = 1_000
NUM_TAG_QUERIES = 100
DATA_SIZE_RANGE = (100, 10000)  # Random file sizes between 100B and 10KB
NUM_TAGS_PER_FILE = 3  # How many tags to assign to each file

# Globals to hold storage backend specific parameters
STORAGE_PARAMS = {
    'fs': {},
    'redis': {
        'host': 'localhost',
        'port': 6379,
        'db': 0,
        'password': None  # Set to None if no password is required
    }
}

# Generate a more diverse tag pool
def generate_tag_pool(num_tags=50):
    """Generate a diverse pool of tags for testing."""
    # Basic categories
    categories = ["color", "shape", "size", "status", "priority", "department", "region", "type", "material", "feature"]
    # Values for each category
    values = {
        "color": ["red", "blue", "green", "yellow", "purple", "black", "white", "orange", "pink", "brown"],
        "shape": ["square", "circle", "triangle", "rectangle", "oval", "hexagon", "star", "diamond"],
        "size": ["tiny", "small", "medium", "large", "huge", "enormous", "microscopic", "gigantic"],
        "status": ["pending", "approved", "rejected", "in_review", "completed", "archived", "draft"],
        "priority": ["low", "medium", "high", "critical", "urgent", "normal"],
        "department": ["sales", "marketing", "engineering", "hr", "finance", "support", "operations"],
        "region": ["north", "south", "east", "west", "central", "global", "local", "international"],
        "type": ["document", "image", "video", "audio", "spreadsheet", "presentation", "code", "data"],
        "material": ["wood", "metal", "plastic", "glass", "paper", "ceramic", "fabric", "composite"],
        "feature": ["searchable", "encrypted", "compressed", "shared", "public", "private", "hidden", "visible"]
    }
    
    # Generate tags by combining categories and values
    tags = []
    for _ in range(num_tags):
        category = random.choice(categories)
        value = random.choice(values[category])
        tags.append(f"{category}:{value}")
    
    # Add some random numeric tags
    for i in range(10):
        tags.append(f"id:{random.randint(1000, 9999)}")
    
    # Add some completely random tags
    for i in range(10):
        random_tag = ''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 10)))
        tags.append(random_tag)
    
    return tags

# Generate our tag pool
TAG_POOL = generate_tag_pool()

# Results storage
results = {
    "fs": {
        "create_time": 0,
        "read_time": 0,
        "query_time": 0,
        "delete_time": 0,
        "create_files_per_sec": 0,
        "read_files_per_sec": 0,
        "total_size": 0,
        "avg_file_size": 0
    },
    "redis": {
        "create_time": 0,
        "read_time": 0,
        "query_time": 0,
        "delete_time": 0,
        "create_files_per_sec": 0,
        "read_files_per_sec": 0,
        "total_size": 0,
        "avg_file_size": 0
    }
}

def generate_random_data(min_size, max_size):
    """Generate random binary data within the specified size range."""
    size = random.randint(min_size, max_size)
    return os.urandom(size)

# Thread-safe counter for progress reporting
class AtomicCounter:
    def __init__(self, initial=0):
        self.value = initial
        self._lock = threading.Lock()
        
    def increment(self, amount=1):
        with self._lock:
            self.value += amount
            return self.value
            
    def get(self):
        with self._lock:
            return self.value

def create_files_worker(worker_id, kv, keys, tag_pool, min_size, max_size, num_tags_per_file, counter, total_files):
    """Worker function for creating files in a thread."""
    results = {
        "file_sizes": [],
        "total_size": 0,
        "success_count": 0,
        "error_count": 0,
        "connection_errors": 0,
        "value_errors": 0,
        "other_errors": 0
    }
    
    for key in keys:
        try:
            # Generate random data
            data = generate_random_data(min_size, max_size)
            results["file_sizes"].append(len(data))
            results["total_size"] += len(data)
            
            # Generate random tags
            tags = list(set(random.sample(tag_pool, min(random.randint(1, num_tags_per_file), len(tag_pool)))))
            
            # Set expiry for 10% of keys
            if random.random() < 0.1:
                ttl = random.randint(3600, 86400)  # 1 hour to 1 day
                kv.set_with_ttl(key, data, ttl, tags)
            else:
                kv.set(key, data, tags)
            
            results["success_count"] += 1
            
            # Progress reporting
            count = counter.increment()
            if count % 1000 == 0:
                print(f"  Created {count}/{total_files} files ({(count/total_files)*100:.1f}%)")
                
        except ConnectionError as e:
            results["connection_errors"] += 1
            results["error_count"] += 1
            print(f"Connection error creating key {key}: {str(e)}")
        except ValueError as e:
            results["value_errors"] += 1
            results["error_count"] += 1
            print(f"Value error creating key {key}: {str(e)}")
        except Exception as e:
            results["other_errors"] += 1
            results["error_count"] += 1
            print(f"Unexpected error creating key {key}: {type(e).__name__}: {str(e)}")
    
    return results

def read_files_worker(worker_id, kv, keys, counter, total_files):
    """Worker function for reading files in a thread."""
    results = {
        "success_count": 0,
        "error_count": 0,
        "not_found_count": 0,
        "connection_errors": 0,
        "other_errors": 0
    }
    
    for key in keys:
        try:
            value = kv.get(key)
            if value:
                results["success_count"] += 1
            else:
                print(f"Warning: Key {key} not found")
                results["not_found_count"] += 1
                results["error_count"] += 1
            
            # Progress reporting
            count = counter.increment()
            if count % 100 == 0:
                print(f"  Read {count}/{total_files} files ({(count/total_files)*100:.1f}%)")
                
        except KeyError as e:
            # Expected behavior for missing keys
            results["not_found_count"] += 1
            results["error_count"] += 1
            print(f"Key {key} not found: {str(e)}")
        except ConnectionError as e:
            results["connection_errors"] += 1
            results["error_count"] += 1
            print(f"Connection error reading key {key}: {str(e)}")
        except Exception as e:
            results["other_errors"] += 1
            results["error_count"] += 1
            print(f"Unexpected error reading key {key}: {type(e).__name__}: {str(e)}")
    
    return results

def query_tags_worker(worker_id, kv, tags, counter, total_queries):
    """Worker function for querying by tags in a thread."""
    results = {
        "success_count": 0,
        "error_count": 0,
        "connection_errors": 0,
        "format_errors": 0,
        "other_errors": 0,
        "results_count": [],
        "query_times": []
    }
    
    for tag in tags:
        try:
            start_time = time.time()
            results_by_tag = kv.query_by_tags([tag])
            query_time = time.time() - start_time
            
            results["success_count"] += 1
            results["results_count"].append(len(results_by_tag))
            results["query_times"].append(query_time)
            
            # Progress reporting
            count = counter.increment()
            if count % 10 == 0:
                print(f"  Executed {count}/{total_queries} queries ({(count/total_queries)*100:.1f}%)")
                print(f"  Query for tag '{tag}' returned {len(results_by_tag)} results in {query_time:.4f}s")
                
        except ConnectionError as e:
            results["connection_errors"] += 1
            results["error_count"] += 1
            print(f"Connection error executing tag query for '{tag}': {str(e)}")
        except ValueError as e:
            results["format_errors"] += 1
            results["error_count"] += 1
            print(f"Format error executing tag query for '{tag}': {str(e)}")
        except Exception as e:
            results["other_errors"] += 1
            results["error_count"] += 1
            print(f"Unexpected error executing tag query for '{tag}': {type(e).__name__}: {str(e)}")
    
    return results

def delete_files_worker(worker_id, kv, keys, counter, total_files):
    """Worker function for deleting files in a thread."""
    results = {
        "success_count": 0,
        "error_count": 0,
        "not_found_count": 0,
        "connection_errors": 0,
        "other_errors": 0
    }
    
    for key in keys:
        try:
            kv.delete(key)
            results["success_count"] += 1
            
            # Progress reporting
            count = counter.increment()
            if count % 1000 == 0:
                print(f"  Deleted {count}/{total_files} files ({(count/total_files)*100:.1f}%)")
                
        except KeyError as e:
            # Not found is not critical for deletion
            results["not_found_count"] += 1
            print(f"Key {key} not found during deletion: {str(e)}")
        except ConnectionError as e:
            results["connection_errors"] += 1
            results["error_count"] += 1
            print(f"Connection error deleting key {key}: {str(e)}")
        except Exception as e:
            results["other_errors"] += 1
            results["error_count"] += 1
            print(f"Unexpected error deleting key {key}: {type(e).__name__}: {str(e)}")
    
    return results

def check_key_exists(kv, key, timeout=5):
    """
    Helper function to check if a key exists in the KeyValueStore.
    
    Args:
        kv: KeyValueStore instance
        key: Key to check
        timeout: Timeout in seconds for the operation
        
    Returns:
        bool: True if key exists, False otherwise
        
    Raises:
        ConnectionError: If the storage backend connection fails
        RuntimeError: For other critical errors that should halt the test
    """
    try:
        # Set a timer to prevent hanging
        start_time = time.time()
        
        # Try to get the key - if it succeeds, the key exists
        kv.get(key)
        
        # Check if operation took too long
        if time.time() - start_time > timeout:
            print(f"Warning: Key existence check for {key} timed out after {timeout}s")
            return False
            
        return True
    except KeyError:
        # Key doesn't exist - expected exception
        return False
    except ConnectionError as e:
        # Connection errors should be propagated
        print(f"Connection error checking key {key}: {str(e)}")
        raise
    except Exception as e:
        # Log but don't propagate other errors
        print(f"Error checking key {key}: {type(e).__name__}: {str(e)}")
        # Only raise runtime errors and critical exceptions
        if isinstance(e, (RuntimeError, SystemError, MemoryError)):
            raise
        return False

def run_backend_test(backend_type, num_threads):
    """Run tests for a specific backend."""
    print(f"\n{'='*50}")
    print(f"Starting stress test for {backend_type.upper()} backend with {num_threads} threads")
    print(f"{'='*50}\n")
    
    # Setup
    data_folder = f"./data/stress_test_{backend_type}"
    os.makedirs(data_folder, exist_ok=True)
    
    # Initialize the backend storage
    sync = None
    kv = None
    
    try:
        # Initialize synchronization
        sync = KeyValueSync(flush_interval_seconds=5)
        
        # Check Redis connection parameters if using Redis
        if backend_type == 'redis':
            redis_params = STORAGE_PARAMS['redis']
            print(f"Using Redis at {redis_params['host']}:{redis_params['port']} DB:{redis_params['db']}")
            
            # Try to verify Redis connection before proceeding
            try:
                # Create a temporary storage just to test connection
                from storage_backends import StorageFactory
                temp_storage = StorageFactory.create_storage('redis', **redis_params)
                if not hasattr(temp_storage, '_ensure_connection') or not temp_storage._ensure_connection():
                    print("Warning: Redis connection test failed. Test may fail.")
            except Exception as e:
                print(f"Error testing Redis connection: {type(e).__name__}: {str(e)}. Test may fail.")
        
        # Initialize KeyValueStore
        kv = KeyValueStore(
            data_folder_path=data_folder,
            db="stress_test",
            buffer_size_mb=10,
            namespace="test",
            sync=sync,
            compression_enabled=True,
            storage_backend=backend_type  # Use the backend type as a string
        )
        
        # If using Redis, update storage connection parameters directly
        if backend_type == 'redis' and hasattr(kv.storage, 'connection_params'):
            # The storage object already exists, but we need to update its connection params
            kv.storage.connection_params.update(STORAGE_PARAMS['redis'])
            # Reconnect with new parameters
            if not kv.storage._connect():
                print("Error: Failed to connect to Redis. Aborting test.")
                return
        
        sync.register_store(kv)
        sync.start()
        
        # Generate all keys
        keys = [f"key{i}" for i in range(NUM_FILES)]
        created_keys = []  # Will hold successfully created keys
        
        # 1. Create files with random data and tags using multiple threads
        print(f"Creating {NUM_FILES} files using {num_threads} threads...")
        
        # Prepare for multi-threaded creation
        start_time = time.time()
        
        # Divide keys among threads
        keys_per_thread = [keys[i::num_threads] for i in range(num_threads)]
        counter = AtomicCounter()
        
        # Track overall errors to abort if too many failures
        total_errors = 0
        error_threshold = NUM_FILES * 0.2  # 20% error threshold
        
        # Create and submit tasks
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all create tasks
            create_futures = []
            for i in range(num_threads):
                future = executor.submit(
                    create_files_worker, 
                    i, 
                    kv, 
                    keys_per_thread[i], 
                    TAG_POOL, 
                    DATA_SIZE_RANGE[0], 
                    DATA_SIZE_RANGE[1], 
                    NUM_TAGS_PER_FILE, 
                    counter, 
                    NUM_FILES
                )
                create_futures.append(future)
            
            # Wait for all tasks to complete and gather results
            create_results = []
            for future in concurrent.futures.as_completed(create_futures):
                try:
                    result = future.result()
                    create_results.append(result)
                    
                    # Check error threshold
                    total_errors += result.get("error_count", 0)
                    if total_errors > error_threshold:
                        print(f"Error threshold exceeded ({total_errors} errors > {error_threshold}). Aborting test.")
                        raise RuntimeError("Too many errors during creation.")
                        
                except Exception as e:
                    print(f"Thread encountered a critical error: {type(e).__name__}: {str(e)}")
                    # We'll continue, but report the error
        
        # Force a flush to ensure all data is written
        try:
            kv.flush()
        except Exception as e:
            print(f"Error flushing data: {type(e).__name__}: {str(e)}")
            # Continue with test, but note the error
        
        end_time = time.time()
        create_time = end_time - start_time
        
        # Aggregate results
        if create_results:
            total_size = sum(r.get("total_size", 0) for r in create_results)
            file_sizes = [size for r in create_results for size in r.get("file_sizes", [])]
            total_success = sum(r.get("success_count", 0) for r in create_results)
            total_errors = sum(r.get("error_count", 0) for r in create_results)
            
            # Build list of successfully created keys with timeout protection
            created_keys = []
            verification_errors = 0
            for i in range(NUM_FILES):
                key = f"key{i}"
                try:
                    if check_key_exists(kv, key):
                        created_keys.append(key)
                except Exception as e:
                    verification_errors += 1
                    if verification_errors > 10:  # Limit number of errors to report
                        print(f"Too many verification errors ({verification_errors}). Aborting verification.")
                        break
            
            # Record results
            results[backend_type]["create_time"] = create_time
            results[backend_type]["create_files_per_sec"] = total_success / create_time if total_success else 0
            results[backend_type]["total_size"] = total_size
            results[backend_type]["avg_file_size"] = statistics.mean(file_sizes) if file_sizes else 0
            
            print(f"Creation completed in {create_time:.2f} seconds")
            print(f"Successfully created {total_success} files ({total_errors} errors)")
            print(f"Verified {len(created_keys)} keys exist")
            print(f"Average throughput: {total_success / create_time:.2f} files/second")
        else:
            print("No creation results available. Skipping remaining tests.")
            return
        
        # 2. Read random files using multiple threads
        num_reads = min(NUM_READS, len(created_keys))
        if num_reads == 0:
            print("No keys to read. Skipping read test.")
        else:
            print(f"\nReading {num_reads} random files using {num_threads} threads...")
            
            # Select random keys to read
            read_keys = random.sample(created_keys, num_reads)
            # Divide keys among threads
            read_keys_per_thread = [read_keys[i::num_threads] for i in range(num_threads)]
            counter = AtomicCounter()
            
            start_time = time.time()
            
            # Create and submit tasks
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                # Submit all read tasks
                read_futures = []
                for i in range(num_threads):
                    future = executor.submit(
                        read_files_worker, 
                        i, 
                        kv, 
                        read_keys_per_thread[i], 
                        counter, 
                        num_reads
                    )
                    read_futures.append(future)
                
                # Wait for all tasks to complete and gather results
                read_results = []
                total_errors = 0
                for future in concurrent.futures.as_completed(read_futures):
                    try:
                        result = future.result()
                        read_results.append(result)
                        
                        # Check error threshold
                        total_errors += result.get("error_count", 0)
                        if total_errors > num_reads * 0.5:  # 50% error threshold for reads
                            print(f"Read error threshold exceeded. Aborting read test.")
                            break
                            
                    except Exception as e:
                        print(f"Thread encountered a critical error: {type(e).__name__}: {str(e)}")
            
            end_time = time.time()
            read_time = end_time - start_time
            
            # Aggregate results
            if read_results:
                successful_reads = sum(r.get("success_count", 0) for r in read_results)
                read_errors = sum(r.get("error_count", 0) for r in read_results)
                
                # Record results
                results[backend_type]["read_time"] = read_time
                results[backend_type]["read_files_per_sec"] = successful_reads / read_time if successful_reads > 0 else 0
                
                print(f"Read completed in {read_time:.2f} seconds")
                print(f"Successfully read {successful_reads} files ({read_errors} errors)")
                print(f"Average read throughput: {successful_reads / read_time:.2f} files/second" if successful_reads > 0 else "No successful reads")
            else:
                print("No read results available. Skipping tag query test.")
                return
        
        # 3. Query by tags using multiple threads
        if not TAG_POOL:
            print("No tags available. Skipping tag query test.")
        else:
            print(f"\nPerforming {NUM_TAG_QUERIES} tag queries using {num_threads} threads...")
            
            # Prepare tag queries - select random tags
            query_tags = random.sample(TAG_POOL, min(NUM_TAG_QUERIES, len(TAG_POOL)))
            if len(query_tags) < NUM_TAG_QUERIES:
                # If we need more tags than in the pool, repeat some
                query_tags.extend(random.choices(TAG_POOL, k=NUM_TAG_QUERIES-len(query_tags)))
            
            # Divide tag queries among threads
            tags_per_thread = [query_tags[i::num_threads] for i in range(num_threads)]
            counter = AtomicCounter()
            
            start_time = time.time()
            
            # Create and submit tasks
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                # Submit all query tasks
                query_futures = []
                for i in range(num_threads):
                    future = executor.submit(
                        query_tags_worker, 
                        i, 
                        kv, 
                        tags_per_thread[i], 
                        counter, 
                        NUM_TAG_QUERIES
                    )
                    query_futures.append(future)
                
                # Wait for all tasks to complete and gather results
                query_results = []
                total_errors = 0
                for future in concurrent.futures.as_completed(query_futures):
                    try:
                        result = future.result()
                        query_results.append(result)
                        
                        # Check error threshold
                        total_errors += result.get("error_count", 0)
                        if total_errors > NUM_TAG_QUERIES * 0.5:  # 50% error threshold for queries
                            print(f"Query error threshold exceeded. Aborting query test.")
                            break
                            
                    except Exception as e:
                        print(f"Thread encountered a critical error: {type(e).__name__}: {str(e)}")
            
            end_time = time.time()
            query_time = end_time - start_time
            
            # Aggregate results
            if query_results:
                successful_queries = sum(r.get("success_count", 0) for r in query_results)
                query_errors = sum(r.get("error_count", 0) for r in query_results)
                
                # Record results
                results[backend_type]["query_time"] = query_time
                
                print(f"Tag queries completed in {query_time:.2f} seconds")
                print(f"Successfully executed {successful_queries} queries ({query_errors} errors)")
                print(f"Average query time: {query_time / successful_queries:.4f} seconds/query" if successful_queries > 0 else "No successful queries")
            else:
                print("No query results available. Skipping cleanup.")
                return
        
        # 4. Delete all files using multiple threads
        if not created_keys:
            print("No keys to delete. Skipping deletion test.")
        else:
            print(f"\nDeleting {len(created_keys)} files using {num_threads} threads...")
            
            # Divide keys among threads
            delete_keys_per_thread = [created_keys[i::num_threads] for i in range(num_threads)]
            counter = AtomicCounter()
            
            start_time = time.time()
            
            # Create and submit tasks
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                # Submit all delete tasks
                delete_futures = []
                for i in range(num_threads):
                    future = executor.submit(
                        delete_files_worker, 
                        i, 
                        kv, 
                        delete_keys_per_thread[i], 
                        counter, 
                        len(created_keys)
                    )
                    delete_futures.append(future)
                
                # Wait for all tasks to complete and gather results
                delete_results = []
                total_errors = 0
                for future in concurrent.futures.as_completed(delete_futures):
                    try:
                        result = future.result()
                        delete_results.append(result)
                        
                        # Check error threshold
                        total_errors += result.get("error_count", 0)
                        if total_errors > len(created_keys) * 0.5:  # 50% error threshold for deletes
                            print(f"Delete error threshold exceeded. Aborting deletion test.")
                            break
                            
                    except Exception as e:
                        print(f"Thread encountered a critical error: {type(e).__name__}: {str(e)}")
            
            # Force a flush to ensure all deletions are processed
            try:
                kv.flush()
            except Exception as e:
                print(f"Error flushing deletions: {type(e).__name__}: {str(e)}")
            
            end_time = time.time()
            delete_time = end_time - start_time
            
            # Aggregate results
            if delete_results:
                deleted_count = sum(r.get("success_count", 0) for r in delete_results)
                delete_errors = sum(r.get("error_count", 0) for r in delete_results)
                
                # Record results
                results[backend_type]["delete_time"] = delete_time
                
                print(f"Deletion completed in {delete_time:.2f} seconds")
                print(f"Successfully deleted {deleted_count} files ({delete_errors} errors)")
            else:
                print("No deletion results available.")
        
    except Exception as e:
        print(f"Fatal error during {backend_type} test: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Ensure proper cleanup
        try:
            if kv:
                try:
                    kv.flush()
                except Exception:
                    pass
                    
                try:
                    kv.close()
                except Exception:
                    pass
                    
            if sync:
                try:
                    sync.sync_exit()
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"Error during cleanup: {type(e).__name__}: {str(e)}")
            
        print(f"Completed test for {backend_type.upper()} backend.")

def print_summary():
    """Print a summary of the test results."""
    print("\n\n")
    print("="*80)
    print(f"{'STRESS TEST SUMMARY':^80}")
    print("="*80)
    print(f"\nTest completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target files per backend: {NUM_FILES:,}")
    
    # Safe formatting function
    def safe_format(value, format_str="{:.2f}"):
        """
        Safely format a value that might be zero/None or of incorrect type.
        
        Args:
            value: The value to format
            format_str: The format string to use
            
        Returns:
            str: Formatted value or appropriate placeholder
        """
        # Handle None and zero values
        if value is None:
            return "N/A"
            
        # Handle numeric zero values
        if isinstance(value, (int, float)) and value == 0:
            if "{:.0f}" in format_str or "{:d}" in format_str:
                return "0"  # For integer formats, return 0 instead of N/A
            return "N/A"
            
        # Try to apply the format string
        try:
            # Type checking for format compatibility
            if "{:.2f}" in format_str and not isinstance(value, (int, float)):
                return f"Error: expected number, got {type(value).__name__}"
                
            formatted = format_str.format(value)
            
            # Sanity check the formatted output
            if len(formatted) > 20:  # Arbitrary length check
                return f"Error: result too long ({len(formatted)} chars)"
                
            return formatted
        except (ValueError, TypeError) as e:
            return f"Error: {type(e).__name__}"
        except Exception:
            return "Error"
    
    # Format results as a table
    headers = ["Metric", "Filesystem", "Redis"]
    rows = [
        ["Creation time (s)", safe_format(results['fs']['create_time']), safe_format(results['redis']['create_time'])],
        ["Files created per second", safe_format(results['fs']['create_files_per_sec']), safe_format(results['redis']['create_files_per_sec'])],
        [f"Read time for {NUM_READS} files (s)", safe_format(results['fs']['read_time']), safe_format(results['redis']['read_time'])],
        ["Files read per second", safe_format(results['fs']['read_files_per_sec']), safe_format(results['redis']['read_files_per_sec'])],
        ["Tag query time (s)", safe_format(results['fs']['query_time']), safe_format(results['redis']['query_time'])],
        ["Average query time (s)", safe_format(results['fs']['query_time']/NUM_TAG_QUERIES if results['fs']['query_time'] else 0, "{:.4f}"), 
                                 safe_format(results['redis']['query_time']/NUM_TAG_QUERIES if results['redis']['query_time'] else 0, "{:.4f}")],
        ["Deletion time (s)", safe_format(results['fs']['delete_time']), safe_format(results['redis']['delete_time'])],
        ["Total data size (MB)", safe_format(results['fs']['total_size']/1024/1024 if results['fs']['total_size'] else 0), 
                               safe_format(results['redis']['total_size']/1024/1024 if results['redis']['total_size'] else 0)],
        ["Average file size (KB)", safe_format(results['fs']['avg_file_size']/1024 if results['fs']['avg_file_size'] else 0), 
                                 safe_format(results['redis']['avg_file_size']/1024 if results['redis']['avg_file_size'] else 0)]
    ]
    
    # Find the maximum width for each column
    col_widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(3)]
    col_widths[0] = max(30, col_widths[0])  # Ensure metric names have enough space
    
    # Print the header
    header_row = " | ".join(f"{headers[i]:{col_widths[i]}}" for i in range(3))
    print("\n" + header_row)
    print("-" * len(header_row))
    
    # Print the data rows
    for row in rows:
        print(" | ".join(f"{row[i]:{col_widths[i]}}" for i in range(3)))
    
    print("\n" + "="*80)

def main():
    """Run the stress tests."""
    # Parse command line arguments
    args = parse_args()
    
    # Validate arguments
    if args.num_files <= 0:
        print("Error: num-files must be greater than 0. Using default of 1000.")
        args.num_files = 1000
        
    if args.num_reads <= 0:
        print("Error: num-reads must be greater than 0. Using default of 1000.")
        args.num_reads = 1000
        
    if args.num_queries <= 0:
        print("Error: num-queries must be greater than 0. Using default of 100.")
        args.num_queries = 100
        
    if args.min_size <= 0:
        print("Error: min-size must be greater than 0. Using default of 100.")
        args.min_size = 100
        
    if args.max_size <= args.min_size:
        print(f"Error: max-size must be greater than min-size. Using {args.min_size * 10}.")
        args.max_size = args.min_size * 10
        
    if args.tags_per_file <= 0:
        print("Error: tags-per-file must be greater than 0. Using default of 3.")
        args.tags_per_file = 3
    
    # Update configuration based on arguments
    global NUM_FILES, NUM_READS, NUM_TAG_QUERIES, DATA_SIZE_RANGE, NUM_TAGS_PER_FILE, STORAGE_PARAMS
    
    NUM_FILES = args.num_files
    NUM_READS = args.num_reads
    NUM_TAG_QUERIES = args.num_queries
    DATA_SIZE_RANGE = (args.min_size, args.max_size)
    NUM_TAGS_PER_FILE = args.tags_per_file
    
    # Set thread count - use args.threads if specified, otherwise use CPU count
    num_threads = args.threads if args.threads is not None else os.cpu_count()
    # Ensure at least 1 thread and no more than system CPU count * 2
    num_threads = max(1, min(num_threads, os.cpu_count() * 2))
    
    # Update Redis configuration
    STORAGE_PARAMS['redis'] = {
        'host': args.redis_host,
        'port': args.redis_port,
        'db': args.redis_db,
        'password': args.redis_password
    }
    
    # Parse backends to test
    backends = [backend.strip() for backend in args.backends.split(',')]
    valid_backends = ['fs', 'redis']
    
    # Validate backends
    for backend in backends[:]:
        if backend not in valid_backends:
            print(f"Warning: Unknown backend '{backend}'. Removing from test list.")
            backends.remove(backend)
            
    if not backends:
        print("Error: No valid backends specified. Using 'fs' as default.")
        backends = ['fs']
    
    print(f"NADB Stress Test Configuration:")
    print(f"  Files per backend: {NUM_FILES:,}")
    print(f"  Files to read: {NUM_READS:,}")
    print(f"  Tag queries: {NUM_TAG_QUERIES}")
    print(f"  File size range: {DATA_SIZE_RANGE[0]}-{DATA_SIZE_RANGE[1]} bytes")
    print(f"  Max tags per file: {NUM_TAGS_PER_FILE}")
    print(f"  Threads: {num_threads}")
    print(f"  Backends to test: {', '.join(backends)}")
    if 'redis' in backends:
        redis_params = STORAGE_PARAMS['redis']
        print(f"  Redis: {redis_params['host']}:{redis_params['port']} DB:{redis_params['db']}")
    print("\nStarting tests...")
    
    start_time = time.time()
    
    # Run tests for each backend
    for backend in backends:
        # Skip invalid backends (should already be filtered out)
        if backend not in valid_backends:
            print(f"Warning: Unknown backend '{backend}'. Skipping.")
            continue
            
        # Run the test for this backend with proper error handling
        try:
            run_backend_test(backend, num_threads)
        except Exception as e:
            print(f"Fatal error running test for {backend} backend: {type(e).__name__}: {str(e)}")
            print("Continuing with next backend...")
    
    # Print summary
    print_summary()
    
    total_time = time.time() - start_time
    print(f"\nTotal stress test time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")

if __name__ == "__main__":
    main() 