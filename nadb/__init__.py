"""
NADB - Not A Database

A simple key-value store with disk persistence, binary data support,
tagging and data compression.
"""

# Import and re-export the main classes from nakv
from _version import __version__
from nakv import (
    KeyValueStore,
    KeyValueSync,
    KeyValueMetadata,
    PerformanceMetrics,
    StoredValue,
    open_store
)
from storage_backends import StorageFactory

__all__ = [
    "KeyValueStore",
    "KeyValueSync",
    "KeyValueMetadata",
    "PerformanceMetrics",
    "StoredValue",
    "StorageFactory",
    "open_store",
]
