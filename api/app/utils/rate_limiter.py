"""
Rate limiting using Token Bucket algorithm.

This module provides:
- TokenBucket class for rate limiting
- RateLimiterMiddleware for FastAPI
- In-memory storage (can be swapped for Redis)

Configuration:
- capacity: Maximum tokens in bucket (default: 50)
- refill_rate: Tokens added per second (default: ~0.83 for 50/min)
"""
import time
import threading
from typing import Dict, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi import status

from .logger import get_logger, get_request_logger

logger = get_logger(__name__)


class TokenBucket:
    """
    Token Bucket algorithm implementation for rate limiting.
    
    The token bucket algorithm allows bursts up to the bucket capacity
    while maintaining a steady refill rate.
    
    Attributes:
        capacity: Maximum number of tokens in the bucket
        refill_rate: Number of tokens added per second
        tokens: Current number of tokens in the bucket
        last_refill: Timestamp of last token refill
    """
    
    def __init__(
        self,
        capacity: int = 50,
        refill_rate: float = 50 / 60  # ~0.83 tokens per second for 50/minute
    ):
        """
        Initialize the token bucket.
        
        Args:
            capacity: Maximum tokens the bucket can hold (default: 50)
            refill_rate: Tokens added per second (default: ~0.83 for 50/min)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = threading.Lock()
    
    def _refill(self) -> None:
        """
        Refill tokens based on elapsed time since last refill.
        
        Thread-safe operation using a lock.
        """
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on elapsed time
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume (default: 1)
        
        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def get_wait_time(self) -> float:
        """
        Get the time in seconds until a token will be available.
        
        Returns:
            Seconds to wait for 1 token, 0 if tokens available now
        """
        with self._lock:
            self._refill()
            
            if self.tokens >= 1:
                return 0.0
            
            # Calculate time needed to get 1 token
            tokens_needed = 1 - self.tokens
            wait_time = tokens_needed / self.refill_rate
            return wait_time
    
    def get_available_tokens(self) -> float:
        """
        Get the current number of available tokens.
        
        Returns:
            Current token count (may include fractional tokens)
        """
        with self._lock:
            self._refill()
            return self.tokens


class RateLimiter:
    """
    Rate limiter using token bucket algorithm with in-memory storage.
    
    Can be extended to use Redis for distributed rate limiting.
    
    Attributes:
        buckets: Dictionary mapping keys to TokenBucket instances
        capacity: Maximum tokens per bucket
        refill_rate: Tokens added per second
    """
    
    def __init__(
        self,
        capacity: int = 50,
        refill_rate: float = 50 / 60
    ):
        """
        Initialize the rate limiter.
        
        Args:
            capacity: Maximum tokens per key (default: 50)
            refill_rate: Tokens added per second (default: ~0.83 for 50/min)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
    
    def _get_bucket(self, key: str) -> TokenBucket:
        """
        Get or create a token bucket for the given key.
        
        Args:
            key: The rate limit key (e.g., API token, IP address)
        
        Returns:
            TokenBucket instance for the key
        """
        with self._lock:
            if key not in self.buckets:
                self.buckets[key] = TokenBucket(
                    capacity=self.capacity,
                    refill_rate=self.refill_rate
                )
            return self.buckets[key]
    
    def consume(self, key: str, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens for the given key.
        
        Args:
            key: The rate limit key
            tokens: Number of tokens to consume
        
        Returns:
            True if tokens were consumed, False if rate limited
        """
        bucket = self._get_bucket(key)
        return bucket.consume(tokens)
    
    def get_wait_time(self, key: str) -> float:
        """
        Get wait time for the given key.
        
        Args:
            key: The rate limit key
        
        Returns:
            Seconds to wait for a token
        """
        bucket = self._get_bucket(key)
        return bucket.get_wait_time()
    
    def get_remaining(self, key: str) -> int:
        """
        Get remaining tokens for the key.
        
        Args:
            key: The rate limit key
        
        Returns:
            Number of remaining tokens (rounded down)
        """
        bucket = self._get_bucket(key)
        return int(bucket.get_available_tokens())
    
    def reset(self, key: str) -> None:
        """
        Reset the rate limit for a key.
        
        Args:
            key: The rate limit key to reset
        """
        with self._lock:
            if key in self.buckets:
                del self.buckets[key]


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """
    Get the global rate limiter instance.
    
    Returns:
        The global RateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            capacity=50,
            refill_rate=50 / 60  # 50 requests per minute
        )
    return _rate_limiter


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting using token bucket algorithm.
    
    Extracts rate limit key from:
    1. X-API-Token header (if present)
    2. falls back to client IP address
    
    Response headers:
    - X-RateLimit-Limit: Maximum requests per window
    - X-RateLimit-Remaining: Remaining requests in current window
    - X-RateLimit-Reset: Seconds until rate limit resets
    - Retry-After: Seconds to wait if rate limited (in 429 response)
    """
    
    def __init__(
        self,
        app,
        capacity: int = 50,
        refill_rate: float = 50 / 60
    ):
        """
        Initialize the rate limiter middleware.
        
        Args:
            app: FastAPI application
            capacity: Maximum requests per window (default: 50)
            refill_rate: Requests per second (default: ~0.83 for 50/min)
        """
        super().__init__(app)
        self.rate_limiter = RateLimiter(
            capacity=capacity,
            refill_rate=refill_rate
        )
        self.capacity = capacity
    
    def _get_client_key(self, request: Request) -> str:
        """
        Extract the rate limit key from the request.
        
        Priority:
        1. X-API-Token header
        2. X-Forwarded-For header (for proxied requests)
        3. Client IP address
        
        Args:
            request: The incoming request
        
        Returns:
            Rate limit key string
        """
        # Try API token first
        api_token = request.headers.get("X-API-Token")
        if api_token:
            return f"token:{api_token}"
        
        # Try forwarded for header
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take first IP in the chain
            client_ip = forwarded_for.split(",")[0].strip()
            return f"ip:{client_ip}"
        
        # Fall back to client IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
    
    async def dispatch(self, request: Request, call_next):
        """Process the request with rate limiting."""
        # Skip rate limiting for health check endpoints
        if request.url.path in ["/", "/health", "/docs", "/api/v1/info"]:
            return await call_next(request)
        
        # Get rate limit key
        key = self._get_client_key(request)
        correlation_id = getattr(request.state, 'correlation_id', 'unknown')
        
        # Check if request is allowed
        if not self.rate_limiter.consume(key):
            wait_time = self.rate_limiter.get_wait_time(key)
            request_logger = get_request_logger(correlation_id)
            request_logger.warning(
                f"Rate limit exceeded for key: {key}",
                extra={
                    "rate_limit_key": key,
                    "wait_time": wait_time,
                }
            )
            
            # Return 429 response
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate Limit Exceeded",
                    "message": f"Too many requests. Please wait {wait_time:.1f} seconds.",
                    "retry_after": int(wait_time) + 1
                },
                headers={
                    "X-RateLimit-Limit": str(self.capacity),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(wait_time) + 1),
                    "Retry-After": str(int(wait_time) + 1)
                }
            )
        
        # Get remaining tokens for response header
        remaining = self.rate_limiter.get_remaining(key)
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(self.capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response
