"""
NADB - Not A Database

A simple key-value store with disk persistence, binary data support,
tagging and data compression.
"""

# Import and re-export the main classes from nakv
from nakv import (
    KeyValueStore,
    KeyValueSync,
    KeyValueMetadata,
    PerformanceMetrics
)
from storage_backends import StorageFactory

__version__ = '0.1.4' 