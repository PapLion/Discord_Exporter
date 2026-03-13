"""
Unit tests for logger utility.

Tests:
- JSONFormatter outputs valid JSON
- Correlation ID is included in logs
- Sensitive data (token, password) is sanitized
- Log levels are correct
"""
import json
import logging
import pytest
from app.utils.logger import (
    JSONFormatter,
    CorrelationLogFilter,
    setup_logger,
    get_logger,
    get_request_logger,
    SENSITIVE_FIELDS
)


class TestJSONFormatter:
    """Tests for JSONFormatter class."""
    
    def test_outputs_valid_json(self):
        """Test that formatter outputs valid JSON."""
        formatter = JSONFormatter(include_extra=False)
        
        # Create a log record
        logger = logging.getLogger("test")
        logger.setLevel(logging.INFO)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
    
    def test_includes_timestamp(self):
        """Test that timestamp is included in output."""
        formatter = JSONFormatter(include_extra=False)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "timestamp" in parsed
        assert parsed["timestamp"] is not None
    
    def test_includes_correlation_id(self):
        """Test that correlation ID is included when present."""
        formatter = JSONFormatter(include_extra=False)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        # Add correlation ID to record
        record.correlation_id = "test-correlation-123"
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "correlation_id" in parsed
        assert parsed["correlation_id"] == "test-correlation-123"
    
    def test_no_correlation_id_when_missing(self):
        """Test that correlation_id is not in output when not present."""
        formatter = JSONFormatter(include_extra=False)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        # Should not have correlation_id key
        assert "correlation_id" not in parsed
    
    def test_sanitizes_token_in_extra(self):
        """Test that token field is sanitized in extra."""
        formatter = JSONFormatter(include_extra=True)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        # Add extra with sensitive data
        record.token = "secret-token-123"
        record.password = "secret-password"
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "extra" in parsed
        assert parsed["extra"]["token"] == "[REDACTED]"
        assert parsed["extra"]["password"] == "[REDACTED]"
    
    def test_sanitizes_api_key(self):
        """Test that api_key field is sanitized."""
        formatter = JSONFormatter(include_extra=True)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        record.api_key = "sk-1234567890"
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert parsed["extra"]["api_key"] == "[REDACTED]"
    
    def test_sanitizes_nested_sensitive_data(self):
        """Test that sensitive data in nested dicts is sanitized."""
        formatter = JSONFormatter(include_extra=True)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        record.request_data = {
            "user": "john",
            "token": "secret-token",
            "nested": {
                "password": "nested-password"
            }
        }
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert parsed["extra"]["request_data"]["token"] == "[REDACTED]"
        assert parsed["extra"]["request_data"]["nested"]["password"] == "[REDACTED]"
        # Non-sensitive data should remain
        assert parsed["extra"]["request_data"]["user"] == "john"
    
    def test_log_levels_correct(self):
        """Test that different log levels are output correctly."""
        formatter = JSONFormatter(include_extra=False)
        
        for level, level_name in [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL")
        ]:
            record = logging.LogRecord(
                name="test_logger",
                level=level,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None
            )
            
            result = formatter.format(record)
            parsed = json.loads(result)
            
            assert parsed["level"] == level_name
    
    def test_exception_info_included(self):
        """Test that exception info is included when present."""
        formatter = JSONFormatter(include_extra=False)
        
        try:
            raise ValueError("Test error")
        except ValueError:
            exc_info = sys.exc_info()
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info
        )
        
        result = formatter.format(record)
        parsed = json.loads(result)
        
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "Test error" in parsed["exception"]


class TestCorrelationLogFilter:
    """Tests for CorrelationLogFilter class."""
    
    def test_adds_correlation_id_to_record(self):
        """Test that filter adds correlation ID to record."""
        correlation_id = "test-correlation-123"
        filter_obj = CorrelationLogFilter(correlation_id)
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        
        result = filter_obj.filter(record)
        
        assert result is True
        assert record.correlation_id == correlation_id
    
    def test_does_not_overwrite_existing_correlation_id(self):
        """Test that existing correlation ID is not overwritten."""
        filter_obj = CorrelationLogFilter("filter-correlation")
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None
        )
        record.correlation_id = "existing-correlation"
        
        result = filter_obj.filter(record)
        
        assert result is True
        assert record.correlation_id == "existing-correlation"


class TestSetupLogger:
    """Tests for setup_logger function."""
    
    def test_returns_logger_instance(self):
        """Test that setup_logger returns a logger."""
        logger = setup_logger("test_logger", level="INFO", json_format=False)
        
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_logger"
    
    def test_sets_correct_level(self):
        """Test that logger level is set correctly."""
        logger = setup_logger("test_level", level="DEBUG", json_format=False)
        
        assert logger.level == logging.DEBUG
    
    def test_json_format_enabled(self):
        """Test that JSON formatter is used when enabled."""
        logger = setup_logger("test_json", level="INFO", json_format=True)
        
        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)
    
    def test_json_format_disabled(self):
        """Test that standard formatter is used when JSON disabled."""
        logger = setup_logger("test_standard", level="INFO", json_format=False)
        
        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        assert not isinstance(handler.formatter, JSONFormatter)


class TestGetRequestLogger:
    """Tests for get_request_logger function."""
    
    def test_returns_logger_with_correlation(self):
        """Test that request logger has correlation ID."""
        correlation_id = "request-123"
        logger = get_request_logger(correlation_id)
        
        assert isinstance(logger, logging.Logger)
        assert correlation_id in logger.name
    
    def test_different_correlation_ids_create_different_loggers(self):
        """Test that different correlation IDs create different loggers."""
        logger1 = get_request_logger("corr-1")
        logger2 = get_request_logger("corr-2")
        
        assert logger1.name != logger2.name


import sys
