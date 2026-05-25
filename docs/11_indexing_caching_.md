# Indexing And Caching

`IndexManager` keeps an in-memory tag index and LRU caches for query results and metadata.

```python
result = store.query_by_tags_advanced(
    tags=["user", "active"],
    operator="AND",
    page=1,
    page_size=100,
)
```

The result includes:

- `keys`
- `total_count`
- `page`
- `page_size`
- `has_more`

You can inspect and maintain indexes:

```python
store.optimize_indexes()
store.rebuild_indexes()
store.clear_caches()

stats = store.get_stats()
cache_stats = stats["cache_stats"]
```

Indexes are rebuilt from metadata when the store starts. Redis and filesystem metadata use the same query contract.

`0.3.0` adds custom indexes and a fluent query builder:

```python
store.set_json("user:1", {"status": "active"})
store.create_index("status")
store.query_index("status", "active")
store.query().where("content_type", "application/json").order_by("key").keys()
```

Cache TTL and approximate memory caps can be configured with `cache_ttl_seconds` and `max_cache_memory_bytes`.
