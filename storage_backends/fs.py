"""
File System Storage Backend for NADB Key-Value Store.

This module implements a file-based storage backend that saves data to the local filesystem.
"""
import os
import logging
import zlib

# Constants for compression
COMPRESS_MIN_SIZE = 1024  # Only compress files larger than 1KB
COMPRESS_LEVEL = 6  # Medium compression (range is 0-9)

class FileSystemStorage:
    """A storage backend that uses the local filesystem to store data."""
    
    def __init__(self, base_path):
        """
        Initialize the filesystem storage backend.
        
        Args:
            base_path: Base directory for storing files
        """
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        self.logger = logging.getLogger("nadb.fs_storage")
    
    def get_full_path(self, relative_path):
        """
        Convert a relative path to a full path.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            Full path in the filesystem
        """
        full_path = os.path.join(self.base_path, relative_path)
        return full_path
    
    def ensure_directory_exists(self, path):
        """
        Ensure that the directory for the given path exists.
        
        Args:
            path: The full path for which to ensure the directory exists
        """
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
    
    def file_exists(self, relative_path):
        """
        Check if a file exists.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            True if the file exists, False otherwise
        """
        full_path = self.get_full_path(relative_path)
        return os.path.exists(full_path)
    
    def write_data(self, relative_path, data):
        """
        Write data to a file.
        
        Args:
            relative_path: Path relative to the base directory
            data: Binary data to write
        """
        full_path = self.get_full_path(relative_path)
        self.ensure_directory_exists(full_path)
        
        try:
            with open(full_path, 'wb') as file:
                file.write(data)
                
            return True
        except Exception as e:
            self.logger.error(f"Error writing to file {full_path}: {str(e)}")
            return False
    
    def read_data(self, relative_path):
        """
        Read data from a file.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            Binary data from the file, or None if file doesn't exist or error occurs
        """
        full_path = self.get_full_path(relative_path)
        
        if not os.path.exists(full_path):
            return None
            
        try:
            with open(full_path, 'rb') as file:
                return file.read()
        except Exception as e:
            self.logger.error(f"Error reading file {full_path}: {str(e)}")
            return None
    
    def delete_file(self, relative_path):
        """
        Delete a file.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            True if the file was deleted, False otherwise
        """
        full_path = self.get_full_path(relative_path)
        
        if not os.path.exists(full_path):
            return True  # Consider it a success if file doesn't exist
            
        try:
            os.remove(full_path)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting file {full_path}: {str(e)}")
            return False
    
    def get_file_size(self, relative_path):
        """
        Get the size of a file.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            Size of the file in bytes, or 0 if file doesn't exist or error occurs
        """
        full_path = self.get_full_path(relative_path)
        
        if not os.path.exists(full_path):
            return 0
            
        try:
            return os.path.getsize(full_path)
        except Exception as e:
            self.logger.error(f"Error getting file size for {full_path}: {str(e)}")
            return 0
    
    def delete_directory(self, relative_path):
        """
        Delete a directory and all its contents.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            True if the directory was deleted, False otherwise
        """
        full_path = self.get_full_path(relative_path)
        
        if not os.path.exists(full_path):
            return True  # Consider it a success if directory doesn't exist
            
        try:
            # Walk through directory and delete files
            for root, dirs, files in os.walk(full_path, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
                    
            # Finally remove the directory itself
            if os.path.exists(full_path):
                os.rmdir(full_path)
                
            return True
        except Exception as e:
            self.logger.error(f"Error deleting directory {full_path}: {str(e)}")
            return False
    
    def compress_data(self, data, compression_enabled):
        """
        Compress data if appropriate.
        
        Args:
            data: Binary data to potentially compress
            compression_enabled: Whether compression is enabled
            
        Returns:
            Compressed data with header or original data
        """
        if not compression_enabled or len(data) <= COMPRESS_MIN_SIZE:
            return data
            
        # Add a simple header to indicate compression
        compressed = zlib.compress(data, COMPRESS_LEVEL)
        return b'CMP:' + compressed
    
    def decompress_data(self, data):
        """
        Decompress data if it was compressed.
        
        Args:
            data: Potentially compressed data
            
        Returns:
            Decompressed data
        """
        if not self._is_compressed(data):
            return data
            
        # Skip the compression header
        compressed_data = data[4:]
        return zlib.decompress(compressed_data)
    
    def _is_compressed(self, data):
        """Check if data has the compression header."""
        return data.startswith(b'CMP:')
