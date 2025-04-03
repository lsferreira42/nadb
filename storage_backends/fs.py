"""
File System Storage Backend for NADB Key-Value Store.

This module implements a file-based storage backend that saves data to the local filesystem.
"""
import os
import logging
import zlib
import uuid
import tempfile
import errno
import stat

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
        
        # Verify base directory permissions
        self._check_directory_permissions(base_path)
    
    def _check_directory_permissions(self, directory):
        """
        Check if we have appropriate permissions on the directory.
        
        Args:
            directory: Directory path to check
            
        Returns:
            True if permissions are OK, False otherwise
        """
        try:
            # Check if directory exists
            if not os.path.exists(directory):
                self.logger.warning(f"Directory does not exist: {directory}")
                return False
                
            # Check if it's actually a directory
            if not os.path.isdir(directory):
                self.logger.error(f"Path is not a directory: {directory}")
                return False
                
            # Check read permission
            if not os.access(directory, os.R_OK):
                self.logger.error(f"No read permission on directory: {directory}")
                return False
                
            # Check write permission
            if not os.access(directory, os.W_OK):
                self.logger.error(f"No write permission on directory: {directory}")
                return False
                
            # Check execute permission (needed to list directory contents)
            if not os.access(directory, os.X_OK):
                self.logger.warning(f"No execute permission on directory: {directory}")
                
            # Try creating a temporary file to verify we can actually write
            try:
                temp_file = os.path.join(directory, f".nadb_test_{uuid.uuid4().hex}")
                with open(temp_file, 'wb') as f:
                    f.write(b'test')
                os.remove(temp_file)
            except (IOError, OSError) as e:
                self.logger.error(f"Failed to write test file in directory {directory}: {str(e)}")
                return False
                
            return True
        except Exception as e:
            self.logger.error(f"Error checking directory permissions for {directory}: {str(e)}")
            return False
    
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
            
        Returns:
            True if directory exists or was created, False otherwise
        """
        directory = os.path.dirname(path)
        try:
            os.makedirs(directory, exist_ok=True)
            return self._check_directory_permissions(directory)
        except (IOError, OSError) as e:
            self.logger.error(f"Failed to create directory {directory}: {str(e)}")
            return False
    
    def file_exists(self, relative_path):
        """
        Check if a file exists.
        
        Args:
            relative_path: Path relative to the base directory
            
        Returns:
            True if the file exists, False otherwise
        """
        full_path = self.get_full_path(relative_path)
        return os.path.exists(full_path) and os.path.isfile(full_path)
    
    def write_data(self, relative_path, data):
        """
        Write data to a file using atomic operations.
        
        Uses a temporary file and rename operation to ensure atomicity.
        
        Args:
            relative_path: Path relative to the base directory
            data: Binary data to write
            
        Returns:
            True if successful, False otherwise
        """
        full_path = self.get_full_path(relative_path)
        
        # Make sure the target directory exists
        if not self.ensure_directory_exists(full_path):
            self.logger.error(f"Cannot write to {full_path}: directory creation or permission check failed")
            return False
        
        # Create a temporary file in the same directory as the target file
        directory = os.path.dirname(full_path)
        temp_filename = None
        temp_file = None
        
        try:
            # Create a temporary file in the same directory for atomic move
            temp_fd, temp_filename = tempfile.mkstemp(dir=directory, prefix='.nadb_temp_')
            
            # Write data to the temporary file
            with os.fdopen(temp_fd, 'wb') as temp_file:
                temp_file.write(data)
                temp_file.flush()
                os.fsync(temp_fd)  # Ensure data is physically written to disk
                
            # Set permissions on the temporary file to match the target or sensible defaults
            try:
                # Try to preserve permissions if the target file exists
                if os.path.exists(full_path):
                    mode = stat.S_IMODE(os.stat(full_path).st_mode)
                    os.chmod(temp_filename, mode)
                else:
                    # Set default permissions (readable/writable by owner, readable by others)
                    os.chmod(temp_filename, 0o644)
            except OSError as e:
                self.logger.warning(f"Failed to set permissions on {temp_filename}: {str(e)}")
                
            # Atomic rename (will replace existing file if present)
            # On POSIX systems, this is an atomic operation
            os.rename(temp_filename, full_path)
            
            return True
            
        except (IOError, OSError) as e:
            self.logger.error(f"Error writing to file {full_path}: {str(e)}")
            # Clean up the temporary file if still exists
            if temp_filename and os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except Exception:
                    pass  # Ignore errors in cleanup
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
            
        if not os.path.isfile(full_path):
            self.logger.error(f"Path exists but is not a file: {full_path}")
            return None
            
        if not os.access(full_path, os.R_OK):
            self.logger.error(f"No read permission for file: {full_path}")
            return None
            
        try:
            with open(full_path, 'rb') as file:
                return file.read()
        except (IOError, OSError) as e:
            error_type = "Permission denied" if e.errno == errno.EACCES else str(e)
            self.logger.error(f"Error reading file {full_path}: {error_type}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error reading file {full_path}: {str(e)}")
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
