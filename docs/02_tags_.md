# Tags

Tags are string labels attached to keys. They are stored in metadata and can be queried across filesystem and Redis backends.

Tags also work with batch writes, chunk manifests, backup streams, and custom index rebuilds.

```python
store.set_text("user:1:name", "Alice", tags=["user", "profile"])
store.set_json("user:1:prefs", {"theme": "dark"}, tags=["user", "config"])

users = store.query_by_tags(["user"])
profiles = store.query_by_tags(["user", "profile"])
tag_counts = store.list_all_tags()
```

`query_by_tags()` uses AND semantics: every requested tag must be present. `query_by_tags_advanced()` supports AND/OR plus pagination when indexing is enabled.

```python
result = store.query_by_tags_advanced(
    tags=["user", "profile"],
    operator="AND",
    page=1,
    page_size=50,
)
```

Tags must be non-empty strings and are validated with length limits to avoid accidental or malicious oversized metadata.

For richer filtering, combine tags with the query builder:

```python
keys = store.query().tag("user").where("content_type", "application/json").limit(50).keys()
```
