"""
Backup and recovery system for NADB with incremental backups and integrity verification.
"""
import os
import json
import gzip
import hashlib
import shutil
import time
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import threading

from logging_config import LoggingConfig


@dataclass
class BackupMetadata:
    """Metadata for a backup."""
    backup_id: str
    timestamp: str
    backup_type: str  # 'full' or 'incremental'
    source_db: str
    source_namespace: str
    file_count: int
    total_size: int
    checksum: str
    parent_backup_id: Optional[str] = None
    compression: bool = True


@dataclass
class BackupItem:
    """Represents a single item in a backup."""
    key: str
    value: str  # Base64 encoded bytes
    tags: List[str]
    metadata: Dict[str, Any]
    checksum: str


class BackupManager:
    """Manages backup and recovery operations for NADB."""
    
    def __init__(self, kv_store, backup_dir: str = "./backups"):
        self.kv_store = kv_store
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.logger = LoggingConfig.get_logger('backup')
        self.perf_logger = LoggingConfig.get_performance_logger('backup')
        self.lock = threading.RLock()
        
        # Load existing backup metadata
        self.backup_metadata: Dict[str, BackupMetadata] = {}
        self._load_backup_metadata()
    
    def create_full_backup(self, backup_id: Optional[str] = None, 
                          compression: bool = True) -> BackupMetadata:
        """Create a full backup of the key-value store."""
        if backup_id is None:
            backup_id = f"full_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        op_id = f"full_backup_{backup_id}"
        self.perf_logger.start_operation(op_id, "full_backup", backup_id=backup_id)
        
        try:
            backup_path = self.backup_dir / backup_id
            backup_path.mkdir(exist_ok=True)
            
            # Get all keys from the store
            all_keys = self._get_all_keys()
            backup_items = []
            total_size = 0
            
            self.logger.info(f"Starting full backup {backup_id} with {len(all_keys)} keys")
            
            # Backup each key
            for i, key in enumerate(all_keys):
                try:
                    # Get data and metadata
                    result = self.kv_store.get_with_metadata(key)
                    value = result['value']
                    metadata = result['metadata']
                    tags = metadata.get('tags', [])
                    
                    # Create backup item
                    item_checksum = self._calculate_checksum(value)
                    backup_item = BackupItem(
                        key=key,
                        value=base64.b64encode(value).decode('utf-8'),
                        tags=tags,
                        metadata=metadata,
                        checksum=item_checksum
                    )
                    backup_items.append(backup_item)
                    total_size += len(value)
                    
                    # Progress logging
                    if (i + 1) % 1000 == 0:
                        self.logger.info(f"Backed up {i + 1}/{len(all_keys)} keys")
                
                except Exception as e:
                    self.logger.error(f"Failed to backup key {key}: {e}")
                    continue
            
            # Write backup data
            data_file = backup_path / "data.json"
            if compression:
                data_file = backup_path / "data.json.gz"
                with gzip.open(data_file, 'wt', encoding='utf-8') as f:
                    json.dump([asdict(item) for item in backup_items], f, default=str)
            else:
                with open(data_file, 'w', encoding='utf-8') as f:
                    json.dump([asdict(item) for item in backup_items], f, default=str)
            
            # Calculate backup checksum
            backup_checksum = self._calculate_file_checksum(data_file)
            
            # Create backup metadata
            backup_meta = BackupMetadata(
                backup_id=backup_id,
                timestamp=datetime.now().isoformat(),
                backup_type='full',
                source_db=self.kv_store.db,
                source_namespace=self.kv_store.namespace,
                file_count=len(backup_items),
                total_size=total_size,
                checksum=backup_checksum,
                compression=compression
            )
            
            # Save metadata
            self._save_backup_metadata(backup_meta)
            
            self.perf_logger.end_operation(op_id, success=True, 
                                         file_count=len(backup_items),
                                         total_size=total_size)
            
            self.logger.info(f"Full backup {backup_id} completed successfully")
            return backup_meta
            
        except Exception as e:
            self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Full backup {backup_id} failed: {e}")
            raise
    
    def create_incremental_backup(self, parent_backup_id: str, 
                                backup_id: Optional[str] = None,
                                compression: bool = True) -> BackupMetadata:
        """Create an incremental backup based on a parent backup."""
        if backup_id is None:
            backup_id = f"inc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if parent_backup_id not in self.backup_metadata:
            raise ValueError(f"Parent backup {parent_backup_id} not found")
        
        parent_backup = self.backup_metadata[parent_backup_id]
        parent_timestamp = datetime.fromisoformat(parent_backup.timestamp)
        
        op_id = f"incremental_backup_{backup_id}"
        self.perf_logger.start_operation(op_id, "incremental_backup", 
                                       backup_id=backup_id,
                                       parent_backup_id=parent_backup_id)
        
        try:
            backup_path = self.backup_dir / backup_id
            backup_path.mkdir(exist_ok=True)
            
            # Get keys modified since parent backup
            modified_keys = self._get_modified_keys_since(parent_timestamp)
            backup_items = []
            total_size = 0
            
            self.logger.info(f"Starting incremental backup {backup_id} with {len(modified_keys)} modified keys")
            
            # Backup modified keys
            for key in modified_keys:
                try:
                    result = self.kv_store.get_with_metadata(key)
                    value = result['value']
                    metadata = result['metadata']
                    tags = metadata.get('tags', [])
                    
                    item_checksum = self._calculate_checksum(value)
                    backup_item = BackupItem(
                        key=key,
                        value=base64.b64encode(value).decode('utf-8'),
                        tags=tags,
                        metadata=metadata,
                        checksum=item_checksum
                    )
                    backup_items.append(backup_item)
                    total_size += len(value)
                
                except Exception as e:
                    self.logger.error(f"Failed to backup key {key}: {e}")
                    continue
            
            # Write backup data
            data_file = backup_path / "data.json"
            if compression:
                data_file = backup_path / "data.json.gz"
                with gzip.open(data_file, 'wt', encoding='utf-8') as f:
                    json.dump([asdict(item) for item in backup_items], f, default=str)
            else:
                with open(data_file, 'w', encoding='utf-8') as f:
                    json.dump([asdict(item) for item in backup_items], f, default=str)
            
            backup_checksum = self._calculate_file_checksum(data_file)
            
            backup_meta = BackupMetadata(
                backup_id=backup_id,
                timestamp=datetime.now().isoformat(),
                backup_type='incremental',
                source_db=self.kv_store.db,
                source_namespace=self.kv_store.namespace,
                file_count=len(backup_items),
                total_size=total_size,
                checksum=backup_checksum,
                parent_backup_id=parent_backup_id,
                compression=compression
            )
            
            self._save_backup_metadata(backup_meta)
            
            self.perf_logger.end_operation(op_id, success=True,
                                         file_count=len(backup_items),
                                         total_size=total_size)
            
            self.logger.info(f"Incremental backup {backup_id} completed successfully")
            return backup_meta
            
        except Exception as e:
            self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Incremental backup {backup_id} failed: {e}")
            raise
    
    def restore_backup(self, backup_id: str, verify_integrity: bool = True,
                      clear_existing: bool = False) -> bool:
        """Restore data from a backup."""
        if backup_id not in self.backup_metadata:
            raise ValueError(f"Backup {backup_id} not found")
        
        backup_meta = self.backup_metadata[backup_id]
        
        op_id = f"restore_{backup_id}"
        self.perf_logger.start_operation(op_id, "restore_backup", backup_id=backup_id)
        
        try:
            # Verify integrity if requested
            if verify_integrity and not self.verify_backup_integrity(backup_id):
                raise RuntimeError(f"Backup {backup_id} failed integrity check")
            
            # Clear existing data if requested
            if clear_existing:
                self.logger.info("Clearing existing data before restore")
                self.kv_store.flushdb()
            
            # Get backup chain (for incremental backups)
            backup_chain = self._get_backup_chain(backup_id)
            
            restored_count = 0
            for chain_backup_id in backup_chain:
                chain_meta = self.backup_metadata[chain_backup_id]
                backup_path = self.backup_dir / chain_backup_id
                
                # Load backup data
                data_file = backup_path / "data.json"
                if chain_meta.compression:
                    data_file = backup_path / "data.json.gz"
                    with gzip.open(data_file, 'rt', encoding='utf-8') as f:
                        backup_data = json.load(f)
                else:
                    with open(data_file, 'r', encoding='utf-8') as f:
                        backup_data = json.load(f)
                
                # Restore each item
                for item_data in backup_data:
                    try:
                        key = item_data['key']
                        # Decode base64 value back to bytes
                        value = base64.b64decode(item_data['value'])
                        tags = item_data.get('tags', [])
                        
                        # Restore the key
                        self.kv_store.set(key, value, tags)
                        restored_count += 1
                        
                        if restored_count % 1000 == 0:
                            self.logger.info(f"Restored {restored_count} keys")
                    
                    except Exception as e:
                        self.logger.error(f"Failed to restore key {item_data.get('key', 'unknown')}: {e}")
                        continue
            
            # Flush to ensure all data is written
            self.kv_store.flush()
            
            self.perf_logger.end_operation(op_id, success=True, restored_count=restored_count)
            self.logger.info(f"Restore from backup {backup_id} completed successfully. Restored {restored_count} keys")
            return True
            
        except Exception as e:
            self.perf_logger.end_operation(op_id, success=False, error=str(e))
            self.logger.error(f"Restore from backup {backup_id} failed: {e}")
            raise
    
    def verify_backup_integrity(self, backup_id: str) -> bool:
        """Verify the integrity of a backup."""
        if backup_id not in self.backup_metadata:
            return False
        
        backup_meta = self.backup_metadata[backup_id]
        backup_path = self.backup_dir / backup_id
        
        try:
            # Check if backup files exist
            data_file = backup_path / "data.json"
            if backup_meta.compression:
                data_file = backup_path / "data.json.gz"
            
            if not data_file.exists():
                self.logger.error(f"Backup data file not found: {data_file}")
                return False
            
            # Verify checksum
            current_checksum = self._calculate_file_checksum(data_file)
            if current_checksum != backup_meta.checksum:
                self.logger.error(f"Backup {backup_id} checksum mismatch")
                return False
            
            # Verify data can be loaded
            if backup_meta.compression:
                with gzip.open(data_file, 'rt', encoding='utf-8') as f:
                    backup_data = json.load(f)
            else:
                with open(data_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
            
            # Verify item count
            if len(backup_data) != backup_meta.file_count:
                self.logger.error(f"Backup {backup_id} item count mismatch")
                return False
            
            self.logger.info(f"Backup {backup_id} integrity verification passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Backup {backup_id} integrity verification failed: {e}")
            return False
    
    def list_backups(self) -> List[BackupMetadata]:
        """List all available backups."""
        return list(self.backup_metadata.values())
    
    def delete_backup(self, backup_id: str, force: bool = False) -> bool:
        """Delete a backup."""
        if backup_id not in self.backup_metadata:
            return False
        
        # Check if other backups depend on this one
        if not force:
            dependents = [b for b in self.backup_metadata.values() 
                         if b.parent_backup_id == backup_id]
            if dependents:
                raise ValueError(f"Cannot delete backup {backup_id}: {len(dependents)} backups depend on it")
        
        try:
            # Remove backup directory
            backup_path = self.backup_dir / backup_id
            if backup_path.exists():
                shutil.rmtree(backup_path)
            
            # Remove from metadata
            del self.backup_metadata[backup_id]
            self._save_all_backup_metadata()
            
            self.logger.info(f"Backup {backup_id} deleted successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False
    
    def cleanup_old_backups(self, keep_days: int = 30, keep_count: int = 10):
        """Clean up old backups based on age and count."""
        cutoff_date = datetime.now() - timedelta(days=keep_days)
        
        # Sort backups by timestamp
        sorted_backups = sorted(self.backup_metadata.values(), 
                              key=lambda b: b.timestamp, reverse=True)
        
        # Keep recent backups and minimum count
        to_delete = []
        for i, backup in enumerate(sorted_backups):
            backup_date = datetime.fromisoformat(backup.timestamp)
            if i >= keep_count and backup_date < cutoff_date:
                to_delete.append(backup.backup_id)
        
        # Delete old backups
        deleted_count = 0
        for backup_id in to_delete:
            try:
                if self.delete_backup(backup_id, force=True):
                    deleted_count += 1
            except Exception as e:
                self.logger.error(f"Failed to delete old backup {backup_id}: {e}")
        
        self.logger.info(f"Cleaned up {deleted_count} old backups")
        return deleted_count
    
    def _get_all_keys(self) -> List[str]:
        """Get all keys from the key-value store."""
        # This is a simplified implementation
        # In practice, you'd need to implement this based on your storage backend
        try:
            if hasattr(self.kv_store, 'get_all_keys'):
                return self.kv_store.get_all_keys()
            else:
                # Fallback: query all metadata
                if self.kv_store.metadata:
                    results = self.kv_store.metadata.query_metadata({
                        'db': self.kv_store.db,
                        'namespace': self.kv_store.namespace
                    })
                    return [r['key'] for r in results]
                else:
                    # For Redis backend, query metadata
                    results = self.kv_store.storage.query_metadata({
                        'db': self.kv_store.db,
                        'namespace': self.kv_store.namespace
                    })
                    return [r['key'] for r in results]
        except Exception as e:
            self.logger.error(f"Failed to get all keys: {e}")
            return []
    
    def _get_modified_keys_since(self, timestamp: datetime) -> List[str]:
        """Get keys modified since a specific timestamp."""
        try:
            if self.kv_store.metadata:
                results = self.kv_store.metadata.query_metadata({
                    'db': self.kv_store.db,
                    'namespace': self.kv_store.namespace,
                    'updated_after': timestamp.isoformat()
                })
                return [r['key'] for r in results]
            else:
                # For Redis backend
                results = self.kv_store.storage.query_metadata({
                    'db': self.kv_store.db,
                    'namespace': self.kv_store.namespace,
                    'updated_after': timestamp.isoformat()
                })
                return [r['key'] for r in results]
        except Exception as e:
            self.logger.error(f"Failed to get modified keys: {e}")
            return []
    
    def _get_backup_chain(self, backup_id: str) -> List[str]:
        """Get the chain of backups needed to restore (from oldest to newest)."""
        chain = []
        current_id = backup_id
        
        while current_id:
            chain.append(current_id)
            backup = self.backup_metadata[current_id]
            current_id = backup.parent_backup_id
        
        return list(reversed(chain))  # Return from oldest to newest
    
    def _calculate_checksum(self, data: bytes) -> str:
        """Calculate SHA-256 checksum of data."""
        return hashlib.sha256(data).hexdigest()
    
    def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA-256 checksum of a file."""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    def _load_backup_metadata(self):
        """Load backup metadata from disk."""
        metadata_file = self.backup_dir / "metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                    for backup_id, meta_dict in data.items():
                        self.backup_metadata[backup_id] = BackupMetadata(**meta_dict)
            except Exception as e:
                self.logger.error(f"Failed to load backup metadata: {e}")
    
    def _save_backup_metadata(self, backup_meta: BackupMetadata):
        """Save backup metadata to disk."""
        self.backup_metadata[backup_meta.backup_id] = backup_meta
        self._save_all_backup_metadata()
    
    def _save_all_backup_metadata(self):
        """Save all backup metadata to disk."""
        metadata_file = self.backup_dir / "metadata.json"
        try:
            with open(metadata_file, 'w') as f:
                data = {backup_id: asdict(meta) for backup_id, meta in self.backup_metadata.items()}
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Failed to save backup metadata: {e}")