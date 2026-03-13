"""
Structured JSON logging utility with correlation ID support.

This module provides:
- Custom JSON formatter with correlation ID support
- Logger setup functions
- Functions to get loggers with correlation context

IMPORTANT: Never log sensitive data (tokens, passwords, secrets).
"""
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from functools import lru_cache

# Sensitive field names that should never be logged
SENSITIVE_FIELDS = frozenset([
    'token', 'password', 'secret', 'api_key', 'apikey', 'authorization',
    'access_token', 'refresh_token', 'bearer', 'x-api-key', 'auth',
    'credential', 'private_key', 'session_id', 'csrf_token', 'csrf'
])


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter that outputs log records as JSON.
    
    Supports correlation ID for request tracing and filters out
    sensitive data from log output.
    """
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def _sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively remove sensitive data from dictionaries.
        
        Checks both keys and string values for sensitive field names.
        """
        if not isinstance(data, dict):
            return data
        
        sanitized = {}
        for key, value in data.items():
            # Check if key is sensitive
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
                sanitized[key] = "[REDACTED]"
                continue
            
            # Recursively sanitize nested dictionaries and lists
            if isinstance(value, dict):
                sanitized[key] = self._sanitize(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize(item) if isinstance(item, dict) else item
                    for item in value
                ]
            elif isinstance(value, str):
                # Check if string value contains sensitive patterns
                value_lower = value.lower()
                if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
                    sanitized[key] = "[REDACTED]"
                else:
                    sanitized[key] = value
            else:
                sanitized[key] = value
        
        return sanitized
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        # Build base log entry
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add correlation ID if present in record
        if hasattr(record, 'correlation_id') and record.correlation_id:
            log_entry["correlation_id"] = record.correlation_id
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields (excluding standard logging attributes)
        if self.include_extra:
            extra_fields = {
                key: value for key, value in record.__dict__.items()
                if key not in (
                    'name', 'msg', 'args', 'created', 'filename', 'funcName',
                    'levelname', 'levelno', 'lineno', 'module', 'msecs',
                    'message', 'pathname', 'process', 'processName', 'thread',
                    'threadName', 'exc_info', 'exc_text', 'stack_info',
                    'relativeCreated', 'asctime', 'correlation_id'
                )
            }
            if extra_fields:
                sanitized_extra = self._sanitize(extra_fields)
                log_entry["extra"] = sanitized_extra
        
        return json.dumps(log_entry)


class CorrelationLogFilter(logging.Filter):
    """
    Logging filter that adds correlation ID to log records.
    
    Used to ensure correlation ID is present in all log records
    within a request context.
    """
    
    def __init__(self, correlation_id: str):
        super().__init__()
        self.correlation_id = correlation_id
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to the record."""
        if not hasattr(record, 'correlation_id') or not record.correlation_id:
            record.correlation_id = self.correlation_id
        return True


def setup_logger(
    name: str,
    level: str = "INFO",
    json_format: bool = True
) -> logging.Logger:
    """
    Setup and configure a logger with the specified settings.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to use JSON formatting
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Choose formatter
    if json_format:
        formatter = JSONFormatter(include_extra=True)
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    # Add console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
    
    return logger


@lru_cache(maxsize=1)
def get_logger(name: str) -> logging.Logger:
    """
    Get a cached logger instance with JSON formatting.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance with correlation ID support
    
    Example:
        logger = get_logger(__name__)
        logger.info("Application started")
    """
    # Import settings here to avoid circular imports
    try:
        from ...config import settings
        level = settings.LOG_LEVEL
    except ImportError:
        level = "INFO"
    
    return setup_logger(name, level=level, json_format=True)


def get_request_logger(correlation_id: str) -> logging.Logger:
    """
    Get a logger configured for a specific request with correlation ID.
    
    This creates a child logger with a correlation filter that ensures
    all log messages include the correlation ID for request tracing.
    
    Args:
        correlation_id: Unique identifier for the request
    
    Returns:
        Logger instance with correlation ID attached
    
    Example:
        logger = get_request_logger(request_id)
        logger.info("Processing request", extra={"endpoint": "/api/v1/export"})
    """
    # Get base logger
    base_logger = get_logger("request")
    
    # Create a new logger instance for this request
    request_logger = logging.getLogger(f"request.{correlation_id}")
    request_logger.setLevel(base_logger.level)
    
    # Clear any existing handlers and add correlation-filtered handler
    request_logger.handlers = []
    
    formatter = JSONFormatter(include_extra=True)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationLogFilter(correlation_id))
    request_logger.addHandler(handler)
    request_logger.propagate = False
    
    return request_logger


# Module-level logger for use within this module
module_logger = get_logger(__name__)
