# Backup And Recovery

Backups export values and metadata to files under the backup directory. Values are base64 encoded so text and binary payloads are preserved.

```python
full = store.create_backup("daily", compression=True)
inc = store.create_incremental_backup(full.backup_id, "daily-inc")
```

Verify and restore:

```python
if store.verify_backup("daily"):
    store.restore_backup("daily", clear_existing=True)
```

Backup records include:

- key,
- base64 value,
- tags,
- metadata,
- item checksum.

Restores preserve tags and restore remaining TTL when `expires_at` metadata is available. Expired items are restored without TTL only when the backup metadata no longer has a positive remaining expiration.

Use `list_backups()`, `delete_backup()`, and `cleanup_old_backups()` from `BackupManager` for retention workflows.

`0.3.0` also supports streaming exports:

```python
store.export_backup_stream("backup.jsonl")
store.import_backup_stream("backup.jsonl")
store.export_backup_tar("backup.tar")
store.prune_backups(keep_last=10, keep_days=30)
```
