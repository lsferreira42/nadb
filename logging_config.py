"""
Advanced logging configuration for NADB with structured logging and performance metrics.
"""
import logging
import logging.handlers
import json
import time
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import threading


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add thread info for concurrent operations
        if hasattr(record, 'thread_id'):
            log_entry['thread_id'] = record.thread_id
        else:
            log_entry['thread_id'] = threading.get_ident()
        
        # Add performance metrics if available
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms
        if hasattr(record, 'operation'):
            log_entry['operation'] = record.operation
        if hasattr(record, 'key_count'):
            log_entry['key_count'] = record.key_count
        if hasattr(record, 'data_size'):
            log_entry['data_size'] = record.data_size
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName', 
                          'processName', 'process', 'getMessage', 'exc_info', 'exc_text', 'stack_info']:
                if not key.startswith('_'):
                    log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


class PerformanceLogger:
    """Logger with built-in performance tracking."""
    
    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)
        self._start_times = {}
        self._lock = threading.Lock()
    
    def start_operation(self, operation_id: str, operation_type: str, **kwargs):
        """Start timing an operation."""
        with self._lock:
            self._start_times[operation_id] = {
                'start_time': time.time(),
                'operation_type': operation_type,
                'metadata': kwargs
            }
    
    def end_operation(self, operation_id: str, success: bool = True, **kwargs):
        """End timing an operation and log the result."""
        with self._lock:
            if operation_id not in self._start_times:
                self.logger.warning(f"Operation {operation_id} not found in start times")
                return
            
            start_info = self._start_times.pop(operation_id)
            duration_ms = (time.time() - start_info['start_time']) * 1000
            
            log_data = {
                'operation': start_info['operation_type'],
                'duration_ms': round(duration_ms, 2),
                'success': success,
                **start_info['metadata'],
                **kwargs
            }
            
            level = logging.INFO if success else logging.ERROR
            self.logger.log(level, f"Operation {start_info['operation_type']} completed", extra=log_data)
    
    def log_metric(self, metric_name: str, value: Any, **kwargs):
        """Log a metric value."""
        log_data = {
            'metric': metric_name,
            'value': value,
            **kwargs
        }
        self.logger.info(f"Metric: {metric_name} = {value}", extra=log_data)


class LoggingConfig:
    """Centralized logging configuration for NADB."""
    
    DEFAULT_CONFIG = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'structured': {
                '()': StructuredFormatter,
            },
            'simple': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'simple',
                'level': 'INFO'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'nadb.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5,
                'formatter': 'structured',
                'level': 'DEBUG'
            }
        },
        'loggers': {
            'nadb': {
                'level': 'INFO',
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'nadb.storage': {
                'level': 'INFO',
                'handlers': ['file'],
                'propagate': False
            },
            'nadb.metadata': {
                'level': 'INFO',
                'handlers': ['file'],
                'propagate': False
            },
            'nadb.sync': {
                'level': 'INFO',
                'handlers': ['file'],
                'propagate': False
            },
            'nadb.performance': {
                'level': 'INFO',
                'handlers': ['file'],
                'propagate': False
            }
        },
        'root': {
            'level': 'WARNING',
            'handlers': ['console']
        }
    }
    
    @classmethod
    def setup_logging(cls, config: Optional[Dict] = None, log_dir: str = "./logs"):
        """Setup logging configuration."""
        if config is None:
            config = cls.DEFAULT_CONFIG.copy()
        
        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        # Update file handler path
        if 'handlers' in config and 'file' in config['handlers']:
            config['handlers']['file']['filename'] = os.path.join(log_dir, 'nadb.log')
        
        # Apply configuration
        logging.config.dictConfig(config)
        
        # Create performance loggers
        cls._setup_performance_loggers()
    
    @classmethod
    def _setup_performance_loggers(cls):
        """Setup specialized performance loggers."""
        # Create performance logger instances
        cls.storage_perf = PerformanceLogger('nadb.performance.storage')
        cls.metadata_perf = PerformanceLogger('nadb.performance.metadata')
        cls.sync_perf = PerformanceLogger('nadb.performance.sync')
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with the specified name."""
        return logging.getLogger(f"nadb.{name}")
    
    @classmethod
    def get_performance_logger(cls, component: str) -> PerformanceLogger:
        """Get a performance logger for the specified component."""
        if component == 'storage':
            return cls.storage_perf
        elif component == 'metadata':
            return cls.metadata_perf
        elif component == 'sync':
            return cls.sync_perf
        else:
            return PerformanceLogger(f'nadb.performance.{component}')


# Initialize logging on import
import logging.config
LoggingConfig.setup_logging()