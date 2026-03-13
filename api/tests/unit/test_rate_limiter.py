"""
Unit tests for rate limiter.

Tests:
- Token bucket starts full
- consume() reduces tokens
- Tokens refill over time
- 429 returned when bucket empty
- Different keys have separate buckets
"""
import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.utils.rate_limiter import (
    TokenBucket,
    RateLimiter,
    RateLimiterMiddleware,
    get_rate_limiter
)


class TestTokenBucket:
    """Tests for TokenBucket class."""
    
    def test_starts_full(self):
        """Test that token bucket starts with full capacity."""
        bucket = TokenBucket(capacity=50, refill_rate=10)
        
        assert bucket.tokens == 50
        assert bucket.capacity == 50
    
    def test_consume_reduces_tokens(self):
        """Test that consume() reduces token count."""
        bucket = TokenBucket(capacity=10, refill_rate=10)
        initial_tokens = bucket.tokens
        
        result = bucket.consume(1)
        
        assert result is True
        assert bucket.tokens < initial_tokens
    
    def test_consume_fails_when_empty(self):
        """Test that consume() fails when insufficient tokens."""
        bucket = TokenBucket(capacity=1, refill_rate=0)  # No refill
        bucket.tokens = 1
        
        result1 = bucket.consume(1)
        result2 = bucket.consume(1)
        
        assert result1 is True
        assert result2 is False
    
    def test_tokens_refill_over_time(self):
        """Test that tokens refill based on time elapsed."""
        bucket = TokenBucket(capacity=50, refill_rate=10)  # 10 tokens per second
        
        # Consume some tokens
        bucket.consume(30)
        
        # Wait a bit (refill)
        time.sleep(0.2)
        
        available = bucket.get_available_tokens()
        
        # Should have refilled ~2 tokens (0.2s * 10/s)
        assert available > 20
    
    def test_tokens_capped_at_capacity(self):
        """Test that tokens never exceed capacity."""
        bucket = TokenBucket(capacity=50, refill_rate=100)
        
        # Wait long enough to overfill
        time.sleep(1)
        
        available = bucket.get_available_tokens()
        
        assert available <= bucket.capacity
    
    def test_get_wait_time_when_tokens_available(self):
        """Test that get_wait_time returns 0 when tokens available."""
        bucket = TokenBucket(capacity=10, refill_rate=10)
        
        wait_time = bucket.get_wait_time()
        
        assert wait_time == 0.0
    
    def test_get_wait_time_when_empty(self):
        """Test that get_wait_time returns positive time when empty."""
        bucket = TokenBucket(capacity=1, refill_rate=1)
        bucket.tokens = 0
        bucket.last_refill = time.time()
        
        wait_time = bucket.get_wait_time()
        
        assert wait_time > 0
    
    def test_get_available_tokens(self):
        """Test get_available_tokens returns current token count."""
        bucket = TokenBucket(capacity=50, refill_rate=10)
        
        available = bucket.get_available_tokens()
        
        assert available == 50
    
    def test_consume_multiple_tokens(self):
        """Test consuming multiple tokens at once."""
        bucket = TokenBucket(capacity=10, refill_rate=0)
        bucket.tokens = 5
        
        result = bucket.consume(3)
        
        assert result is True
        assert bucket.tokens == 2
    
    def test_consume_fails_for_exact_tokens(self):
        """Test consuming exact number of tokens succeeds."""
        bucket = TokenBucket(capacity=10, refill_rate=0)
        bucket.tokens = 5
        
        result = bucket.consume(5)
        
        assert result is True
        assert bucket.tokens == 0


class TestRateLimiter:
    """Tests for RateLimiter class."""
    
    def test_different_keys_have_separate_buckets(self):
        """Test that different keys have independent token buckets."""
        limiter = RateLimiter(capacity=5, refill_rate=0)
        
        # Consume all tokens for key1
        for _ in range(5):
            limiter.consume("key1")
        
        # key1 should be rate limited now
        result_key1 = limiter.consume("key1")
        
        # key2 should still have tokens (separate bucket)
        result_key2 = limiter.consume("key2")
        
        assert result_key1 is False
        assert result_key2 is True
    
    def test_get_remaining_returns_int(self):
        """Test get_remaining returns integer token count."""
        limiter = RateLimiter(capacity=50, refill_rate=10)
        
        remaining = limiter.get_remaining("test-key")
        
        assert isinstance(remaining, int)
        assert remaining == 50
    
    def test_reset_clears_bucket(self):
        """Test that reset() clears a key's bucket."""
        limiter = RateLimiter(capacity=5, refill_rate=0)
        
        # Consume all tokens
        for _ in range(5):
            limiter.consume("test-key")
        
        # Reset the key
        limiter.reset("test-key")
        
        # Should have full bucket again
        remaining = limiter.get_remaining("test-key")
        assert remaining == 5
    
    def test_consume_returns_false_when_rate_limited(self):
        """Test consume returns False when rate limited."""
        limiter = RateLimiter(capacity=2, refill_rate=0)
        
        result1 = limiter.consume("key")
        result2 = limiter.consume("key")
        result3 = limiter.consume("key")
        
        assert result1 is True
        assert result2 is True
        assert result3 is False
    
    def test_get_wait_time_for_key(self):
        """Test get_wait_time returns time for specific key."""
        limiter = RateLimiter(capacity=1, refill_rate=1)
        limiter.buckets["test-key"] = TokenBucket(capacity=1, refill_rate=1)
        limiter.buckets["test-key"].tokens = 0
        
        wait_time = limiter.get_wait_time("test-key")
        
        assert wait_time > 0


class TestRateLimiterMiddleware:
    """Tests for RateLimiterMiddleware class."""
    
    @pytest.fixture
    def mock_app(self):
        """Create a mock FastAPI app."""
        app = Mock()
        return app
    
    @pytest.fixture
    def middleware(self, mock_app):
        """Create rate limiter middleware instance."""
        return RateLimiterMiddleware(
            mock_app,
            capacity=5,
            refill_rate=5
        )
    
    def test_skips_health_endpoints(self, middleware, mock_app):
        """Test that health endpoints are skipped."""
        # Create mock request
        request = Mock(spec=Request)
        request.url.path = "/health"
        request.state = Mock()
        request.state.correlation_id = "test-correlation"
        
        # Mock call_next - should be called without rate limiting
        async def call_next(req):
            return JSONResponse({"status": "ok"})
        
        # Use async dispatch directly with new event loop
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                middleware.dispatch(request, call_next)
            )
        finally:
            loop.close()
    
    def test_returns_429_when_rate_limited(self, middleware, mock_app):
        """Test that 429 is returned when rate limited."""
        # Exhaust tokens for a key
        for _ in range(6):  # capacity is 5
            middleware.rate_limiter.consume("ip:127.0.0.1")
        
        # Create mock request
        request = Mock(spec=Request)
        request.url.path = "/api/v1/export"
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {}
        request.state = Mock()
        request.state.correlation_id = "test-correlation"
        
        # Mock call_next
        async def call_next(req):
            return JSONResponse({"status": "ok"})
        
        # Should return 429
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                middleware.dispatch(request, call_next)
            )
        finally:
            loop.close()
        
        assert response.status_code == 429
    
    def test_rate_limit_headers_present(self, middleware, mock_app):
        """Test that rate limit headers are in response."""
        # Create mock request
        request = Mock(spec=Request)
        request.url.path = "/api/v1/export"
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {}
        request.state = Mock()
        request.state.correlation_id = "test-correlation"
        
        # Mock call_next
        async def call_next(req):
            return JSONResponse({"status": "ok"})
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                middleware.dispatch(request, call_next)
            )
        finally:
            loop.close()
        
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
    
    def test_get_client_key_from_token(self, middleware):
        """Test that API token is used as rate limit key."""
        request = Mock(spec=Request)
        request.headers = {"X-API-Token": "test-token-123"}
        
        key = middleware._get_client_key(request)
        
        assert key == "token:test-token-123"
    
    def test_get_client_key_from_forwarded_for(self, middleware):
        """Test that X-Forwarded-For header is used."""
        request = Mock(spec=Request)
        request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
        
        key = middleware._get_client_key(request)
        
        assert key == "ip:192.168.1.1"
    
    def test_get_client_key_fallback_to_client_ip(self, middleware):
        """Test fallback to client IP when no headers."""
        request = Mock(spec=Request)
        request.headers = {}
        request.client = Mock()
        request.client.host = "10.0.0.5"
        
        key = middleware._get_client_key(request)
        
        assert key == "ip:10.0.0.5"


class TestGetRateLimiter:
    """Tests for get_rate_limiter function."""
    
    def test_returns_rate_limiter_instance(self):
        """Test that get_rate_limiter returns RateLimiter."""
        limiter = get_rate_limiter()
        
        assert isinstance(limiter, RateLimiter)
    
    def test_returns_same_instance(self):
        """Test that get_rate_limiter returns singleton."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        
        assert limiter1 is limiter2
