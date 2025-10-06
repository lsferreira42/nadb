"""
Index management and caching system for NADB with secondary indexes and query optimization.
"""
import threading
import time
from typing import Dict, List, Set, Optional, Any, Tuple, Union
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import json
import sqlite3
from datetime import datetime, timedelta

from logging_config import LoggingConfig


class QueryOperator(Enum):
    """Query operators for complex queries."""
    AND = "and"
    OR = "or"
    NOT = "not"
    IN = "in"
    RANGE = "range"


@dataclass
class QueryCondition:
    """Represents a query condition."""
    field: str
    operator: QueryOperator
    value: Any
    values: Optional[List[Any]] = None  # For IN operator
    min_value: Optional[Any] = None     # For RANGE operator
    max_value: Optional[Any] = None     # For RANGE operator


@dataclass
class QueryResult:
    """Result of a query with pagination support."""
    keys: List[str]
    total_count: int
    page: int
    page_size: int
    has_more: bool
    execution_time_ms: float
    cache_hit: bool = False


@dataclass
class IndexStats:
    """Statistics for an index."""
    index_name: str
    unique_values: int
    total_entries: int
    memory_usage_bytes: int
    hit_count: int
    miss_count: int
    last_updated: datetime
    avg_query_time_ms: float


class LRUCache:
    """Thread-safe LRU cache implementation."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = OrderedDict()
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                value = self.cache.pop(key)
                self.cache[key] = value
                self.hits += 1
                return value
            else:
                self.misses += 1
                return None
    
    def put(self, key: str, value: Any):
        """Put value in cache."""
        with self.lock:
            if key in self.cache:
                # Update existing
                self.cache.pop(key)
            elif len(self.cache) >= self.max_size:
                # Remove least recently used
                self.cache.popitem(last=False)
            
            self.cache[key] = value
    
    def clear(self):
        """Clear the cache."""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = self.hits / total_requests if total_requests > 0 else 0
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': hit_rate
            }


class TagIndex:
    """In-memory index for tags with statistics."""
    
    def __init__(self):
        self.tag_to_keys: Dict[str, Set[str]] = defaultdict(set)
        self.key_to_tags: Dict[str, Set[str]] = defaultdict(set)
        self.tag_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'count': 0,
            'query_count': 0,
            'last_queried': None
        })
        self.lock = threading.RLock()
    
    def add_key(self, key: str, tags: List[str]):
        """Add a key with its tags to the index."""
        with self.lock:
            # Remove old tags for this key
            old_tags = self.key_to_tags.get(key, set())
            for old_tag in old_tags:
                self.tag_to_keys[old_tag].discard(key)
                if not self.tag_to_keys[old_tag]:
                    del self.tag_to_keys[old_tag]
                    del self.tag_stats[old_tag]
                else:
                    self.tag_stats[old_tag]['count'] -= 1
            
            # Add new tags
            self.key_to_tags[key] = set(tags)
            for tag in tags:
                self.tag_to_keys[tag].add(key)
                self.tag_stats[tag]['count'] += 1
    
    def remove_key(self, key: str):
        """Remove a key from the index."""
        with self.lock:
            tags = self.key_to_tags.get(key, set())
            for tag in tags:
                self.tag_to_keys[tag].discard(key)
                if not self.tag_to_keys[tag]:
                    del self.tag_to_keys[tag]
                    del self.tag_stats[tag]
                else:
                    self.tag_stats[tag]['count'] -= 1
            
            if key in self.key_to_tags:
                del self.key_to_tags[key]
    
    def query_tags_and(self, tags: List[str]) -> Set[str]:
        """Query keys that have ALL specified tags."""
        with self.lock:
            if not tags:
                return set()
            
            # Update query statistics
            for tag in tags:
                if tag in self.tag_stats:
                    self.tag_stats[tag]['query_count'] += 1
                    self.tag_stats[tag]['last_queried'] = datetime.now()
            
            # Find intersection of all tag sets
            result_keys = None
            for tag in tags:
                tag_keys = self.tag_to_keys.get(tag, set())
                if result_keys is None:
                    result_keys = tag_keys.copy()
                else:
                    result_keys &= tag_keys
                
                # Early exit if no intersection
                if not result_keys:
                    break
            
            return result_keys or set()
    
    def query_tags_or(self, tags: List[str]) -> Set[str]:
        """Query keys that have ANY of the specified tags."""
        with self.lock:
            if not tags:
                return set()
            
            # Update query statistics
            for tag in tags:
                if tag in self.tag_stats:
                    self.tag_stats[tag]['query_count'] += 1
                    self.tag_stats[tag]['last_queried'] = datetime.now()
            
            # Find union of all tag sets
            result_keys = set()
            for tag in tags:
                result_keys |= self.tag_to_keys.get(tag, set())
            
            return result_keys
    
    def get_tag_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all tags."""
        with self.lock:
            return dict(self.tag_stats)
    
    def get_popular_tags(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most popular tags by query count."""
        with self.lock:
            sorted_tags = sorted(
                self.tag_stats.items(),
                key=lambda x: x[1]['query_count'],
                reverse=True
            )
            return [(tag, stats['query_count']) for tag, stats in sorted_tags[:limit]]


class IndexManager:
    """Manages secondary indexes and query optimization for NADB."""
    
    def __init__(self, kv_store, cache_size: int = 10000):
        self.kv_store = kv_store
        self.logger = LoggingConfig.get_logger('index')
        self.perf_logger = LoggingConfig.get_performance_logger('index')
        
        # Indexes
        self.tag_index = TagIndex()
        
        # Caches
        self.query_cache = LRUCache(cache_size)
        self.metadata_cache = LRUCache(cache_size // 2)
        
        # Statistics
        self.query_stats = defaultdict(lambda: {
            'count': 0,
            'total_time_ms': 0,
            'avg_time_ms': 0,
            'cache_hits': 0
        })
        
        self.lock = threading.RLock()
        
        # Initialize indexes
        self._rebuild_indexes()
    
    def add_key_to_indexes(self, key: str, tags: List[str], metadata: Dict[str, Any]):
        """Add a key to all relevant indexes."""
        with self.lock:
            # Add to tag index
            self.tag_index.add_key(key, tags)
            
            # Cache metadata
            self.metadata_cache.put(key, metadata)
            
            # Clear related query cache entries
            self._invalidate_query_cache(tags)
    
    def remove_key_from_indexes(self, key: str):
        """Remove a key from all indexes."""
        with self.lock:
            # Get tags before removal for cache invalidation
            tags = list(self.tag_index.key_to_tags.get(key, set()))
            
            # Remove from tag index
            self.tag_index.remove_key(key)
            
            # Remove from metadata cache
            if key in self.metadata_cache.cache:
                del self.metadata_cache.cache[key]
            
            # Clear related query cache entries
            self._invalidate_query_cache(tags)
    
    def query_by_tags(self, tags: List[str], operator: QueryOperator = QueryOperator.AND,
                     page: int = 1, page_size: int = 100) -> QueryResult:
        """Query keys by tags with pagination support."""
        start_time = time.time()
        
        # Create cache key
        cache_key = f"tags_{operator.value}_{','.join(sorted(tags))}_{page}_{page_size}"
        
        # Check cache first
        cached_result = self.query_cache.get(cache_key)
        if cached_result:
            cached_result.cache_hit = True
            self.query_stats[f"tags_{operator.value}"]['cache_hits'] += 1
            return cached_result
        
        # Execute query
        if operator == QueryOperator.AND:
            result_keys = self.tag_index.query_tags_and(tags)
        elif operator == QueryOperator.OR:
            result_keys = self.tag_index.query_tags_or(tags)
        else:
            raise ValueError(f"Unsupported operator for tag queries: {operator}")
        
        # Convert to sorted list for consistent pagination
        result_keys_list = sorted(list(result_keys))
        total_count = len(result_keys_list)
        
        # Apply pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_keys = result_keys_list[start_idx:end_idx]
        has_more = end_idx < total_count
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Create result
        result = QueryResult(
            keys=page_keys,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_more=has_more,
            execution_time_ms=execution_time_ms,
            cache_hit=False
        )
        
        # Cache result
        self.query_cache.put(cache_key, result)
        
        # Update statistics
        query_type = f"tags_{operator.value}"
        self.query_stats[query_type]['count'] += 1
        self.query_stats[query_type]['total_time_ms'] += execution_time_ms
        self.query_stats[query_type]['avg_time_ms'] = (
            self.query_stats[query_type]['total_time_ms'] / 
            self.query_stats[query_type]['count']
        )
        
        self.logger.debug(f"Tag query completed: {len(tags)} tags, {total_count} results, {execution_time_ms:.2f}ms")
        
        return result
    
    def complex_query(self, conditions: List[QueryCondition], 
                     page: int = 1, page_size: int = 100) -> QueryResult:
        """Execute complex queries with multiple conditions."""
        start_time = time.time()
        
        # Create cache key
        cache_key = f"complex_{hash(str(conditions))}_{page}_{page_size}"
        
        # Check cache
        cached_result = self.query_cache.get(cache_key)
        if cached_result:
            cached_result.cache_hit = True
            self.query_stats['complex']['cache_hits'] += 1
            return cached_result
        
        # Execute conditions
        result_sets = []
        
        for condition in conditions:
            if condition.field == 'tags':
                if condition.operator == QueryOperator.AND:
                    keys = self.tag_index.query_tags_and(condition.values or condition.value or [])
                elif condition.operator == QueryOperator.OR:
                    keys = self.tag_index.query_tags_or(condition.values or condition.value or [])
                elif condition.operator == QueryOperator.IN:
                    keys = self.tag_index.query_tags_or(condition.values or [])
                else:
                    keys = set()
                result_sets.append(keys)
            else:
                # For other fields, fall back to metadata queries
                keys = self._query_metadata_field(condition)
                result_sets.append(keys)
        
        # Combine results (AND operation between conditions)
        if result_sets:
            final_keys = result_sets[0]
            for keys in result_sets[1:]:
                final_keys &= keys
        else:
            final_keys = set()
        
        # Convert to sorted list and paginate
        result_keys_list = sorted(list(final_keys))
        total_count = len(result_keys_list)
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_keys = result_keys_list[start_idx:end_idx]
        has_more = end_idx < total_count
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        result = QueryResult(
            keys=page_keys,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_more=has_more,
            execution_time_ms=execution_time_ms,
            cache_hit=False
        )
        
        # Cache and update stats
        self.query_cache.put(cache_key, result)
        self.query_stats['complex']['count'] += 1
        self.query_stats['complex']['total_time_ms'] += execution_time_ms
        self.query_stats['complex']['avg_time_ms'] = (
            self.query_stats['complex']['total_time_ms'] / 
            self.query_stats['complex']['count']
        )
        
        return result
    
    def get_index_stats(self) -> Dict[str, IndexStats]:
        """Get statistics for all indexes."""
        stats = {}
        
        # Tag index stats
        tag_stats = self.tag_index.get_tag_stats()
        total_tags = len(tag_stats)
        total_entries = sum(stats['count'] for stats in tag_stats.values())
        total_queries = sum(stats['query_count'] for stats in tag_stats.values())
        
        stats['tag_index'] = IndexStats(
            index_name='tag_index',
            unique_values=total_tags,
            total_entries=total_entries,
            memory_usage_bytes=self._estimate_tag_index_memory(),
            hit_count=total_queries,
            miss_count=0,  # Not tracked for tag index
            last_updated=datetime.now(),
            avg_query_time_ms=self.query_stats.get('tags_and', {}).get('avg_time_ms', 0)
        )
        
        return stats
    
    def get_cache_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get cache statistics."""
        return {
            'query_cache': self.query_cache.get_stats(),
            'metadata_cache': self.metadata_cache.get_stats()
        }
    
    def get_query_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get query execution statistics."""
        return dict(self.query_stats)
    
    def optimize_indexes(self):
        """Optimize indexes based on usage patterns."""
        self.logger.info("Starting index optimization")
        
        # Get popular tags
        popular_tags = self.tag_index.get_popular_tags(20)
        
        # Log optimization suggestions
        if popular_tags:
            self.logger.info(f"Most queried tags: {popular_tags[:5]}")
        
        # Clear old cache entries (keep only recent ones)
        cache_stats = self.query_cache.get_stats()
        if cache_stats['size'] > cache_stats['max_size'] * 0.8:
            # Clear 25% of cache
            with self.query_cache.lock:
                items_to_remove = len(self.query_cache.cache) // 4
                for _ in range(items_to_remove):
                    if self.query_cache.cache:
                        self.query_cache.cache.popitem(last=False)
        
        self.logger.info("Index optimization completed")
    
    def rebuild_indexes(self):
        """Rebuild all indexes from scratch."""
        self.logger.info("Rebuilding indexes")
        self._rebuild_indexes()
        self.logger.info("Index rebuild completed")
    
    def clear_caches(self):
        """Clear all caches."""
        self.query_cache.clear()
        self.metadata_cache.clear()
        self.logger.info("All caches cleared")
    
    def _rebuild_indexes(self):
        """Internal method to rebuild indexes."""
        try:
            # Clear existing indexes
            self.tag_index = TagIndex()
            self.query_cache.clear()
            self.metadata_cache.clear()
            
            # Get all keys and rebuild
            if self.kv_store.metadata:
                # Filesystem backend
                results = self.kv_store.metadata.query_metadata({
                    'db': self.kv_store.db,
                    'namespace': self.kv_store.namespace
                })
            else:
                # Redis backend
                results = self.kv_store.storage.query_metadata({
                    'db': self.kv_store.db,
                    'namespace': self.kv_store.namespace
                })
            
            for result in results:
                key = result['key']
                tags = result.get('tags', [])
                self.tag_index.add_key(key, tags)
                self.metadata_cache.put(key, result)
            
            self.logger.info(f"Rebuilt indexes for {len(results)} keys")
            
        except Exception as e:
            self.logger.error(f"Failed to rebuild indexes: {e}")
    
    def _invalidate_query_cache(self, tags: List[str]):
        """Invalidate query cache entries related to specific tags."""
        # This is a simplified implementation
        # In practice, you'd want more sophisticated cache invalidation
        with self.query_cache.lock:
            keys_to_remove = []
            for cache_key in self.query_cache.cache.keys():
                if any(tag in cache_key for tag in tags):
                    keys_to_remove.append(cache_key)
            
            for key in keys_to_remove:
                self.query_cache.cache.pop(key, None)
    
    def _query_metadata_field(self, condition: QueryCondition) -> Set[str]:
        """Query metadata fields (fallback for non-indexed fields)."""
        try:
            query = {
                'db': self.kv_store.db,
                'namespace': self.kv_store.namespace
            }
            
            if condition.operator == QueryOperator.RANGE:
                if condition.min_value is not None:
                    query[f'min_{condition.field}'] = condition.min_value
                if condition.max_value is not None:
                    query[f'max_{condition.field}'] = condition.max_value
            
            if self.kv_store.metadata:
                results = self.kv_store.metadata.query_metadata(query)
            else:
                results = self.kv_store.storage.query_metadata(query)
            
            return set(r['key'] for r in results)
            
        except Exception as e:
            self.logger.error(f"Failed to query metadata field {condition.field}: {e}")
            return set()
    
    def _estimate_tag_index_memory(self) -> int:
        """Estimate memory usage of tag index."""
        # Rough estimation
        tag_count = len(self.tag_index.tag_to_keys)
        key_count = len(self.tag_index.key_to_tags)
        
        # Estimate: 100 bytes per tag entry + 50 bytes per key entry
        return (tag_count * 100) + (key_count * 50)