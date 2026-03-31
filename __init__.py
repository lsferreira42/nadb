# NADB - Not A Database
# A high-performance key-value store with advanced features

from nakv import KeyValueStore, KeyValueSync, KeyValueMetadata, PerformanceMetrics

# Try to import advanced features, but don't fail if they're not available
try:
    from logging_config import LoggingConfig
    __all__ = ['KeyValueStore', 'KeyValueSync', 'KeyValueMetadata', 'PerformanceMetrics', 'LoggingConfig']
except ImportError:
    __all__ = ['KeyValueStore', 'KeyValueSync', 'KeyValueMetadata', 'PerformanceMetrics']

try:
    from transaction import TransactionManager
    __all__.append('TransactionManager')
except ImportError:
    pass

try:
    from backup_manager import BackupManager
    __all__.append('BackupManager')
except ImportError:
    pass

try:
    from index_manager import IndexManager
    __all__.append('IndexManager')
except ImportError:
    pass

__version__ = "2.0.0"
__author__ = "NADB Contributors"
__description__ = "A high-performance key-value store with advanced features"