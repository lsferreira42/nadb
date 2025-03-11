"""
Storage Backends Package for NADB Key-Value Store.

This package contains storage backend implementations for the NADB key-value store.
Currently supported backends:
- fs: File system storage
"""

from importlib import import_module
import logging

logger = logging.getLogger('storage_backends')

class StorageFactory:
    """Factory for creating storage backends."""
    
    @staticmethod
    def create_storage(backend_type, **kwargs):
        """
        Create a storage backend of the specified type.
        
        Args:
            backend_type: Type of storage backend ('fs' for filesystem, etc.)
            **kwargs: Arguments to pass to the storage backend constructor
            
        Returns:
            An instance of the requested storage backend
        """
        try:
            # Import the appropriate backend module
            backend_module = import_module(f"storage_backends.{backend_type}")
            
            # Map backend types to class names
            backend_classes = {
                "fs": "FileSystemStorage",
                "redis": "RedisStorage",
                "memcache": "MemcacheStorage"
            }
            
            # Get the class name from the mapping or use default naming convention
            if backend_type in backend_classes:
                class_name = backend_classes[backend_type]
            else:
                # Convert 'some_backend' to 'SomeBackendStorage'
                class_name = "".join(part.capitalize() for part in backend_type.split("_")) + "Storage"
            
            # Get the class from the module
            storage_class = getattr(backend_module, class_name)
            
            # Create and return an instance
            return storage_class(**kwargs)
            
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to load storage backend '{backend_type}': {str(e)}")
            # Fall back to filesystem storage
            if backend_type != "fs":
                logger.info("Falling back to filesystem storage")
                return StorageFactory.create_storage("fs", **kwargs)
            else:
                raise ValueError(f"Cannot create storage backend: {str(e)}") 