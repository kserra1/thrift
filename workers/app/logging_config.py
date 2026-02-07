"""
Structured logging configuration.

All logs are output as JSON with consistent fields:
- timestamp
- level
- message
- correlation_id (request ID for tracing)
- model_name, model_version (when relevant)
- duration (for operations)
"""
import logging
import sys
from pythonjsonlogger import jsonlogger
from contextvars import ContextVar
from typing import Optional
import uuid

# Context variable for request correlation ID
# This persists across async calls in the same request
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to all log records."""
    
    def filter(self, record):
        record.correlation_id = correlation_id_var.get() or 'none'
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that adds standard fields.
    
    Output format:
    {
        "timestamp": "2024-02-06T10:30:45.123Z",
        "level": "INFO",
        "name": "workers.app.main",
        "message": "Model loaded successfully",
        "correlation_id": "abc-123-def",
        "model_name": "iris",
        "model_version": "v1",
        "duration_ms": 1234.5
    }
    """
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp
        log_record['timestamp'] = self.formatTime(record, self.datefmt)
        
        # Add level
        log_record['level'] = record.levelname
        
        # Add logger name
        log_record['name'] = record.name
        
        # Add correlation ID
        log_record['correlation_id'] = getattr(record, 'correlation_id', 'none')


def setup_logging(level: str = "INFO"):
    """
    Configure structured JSON logging.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create handler for stdout
    handler = logging.StreamHandler(sys.stdout)
    
    # Set JSON formatter
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Add correlation ID filter
    handler.addFilter(CorrelationIdFilter())
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []
    root_logger.addHandler(handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


def set_correlation_id(correlation_id: Optional[str] = None):
    """
    Set correlation ID for the current async context.
    
    Args:
        correlation_id: ID to use, or None to generate a new one
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    correlation_id_var.set(correlation_id)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return correlation_id_var.get()


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.
    
    Usage:
        logger = get_logger(__name__)
        logger.info("Model loaded", extra={"model_name": "iris", "duration_ms": 123.4})
    """
    return logging.getLogger(name)