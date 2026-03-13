"""
Typed Discord API client with proper error handling and rate limiting.

This module provides:
- Async HTTP client using httpx
- Typed methods for Discord API operations
- Rate limit handling with Retry-After header
- Custom exceptions for Discord API errors
- Logging with correlation ID support
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, Dict
import httpx
import logging

# Import from local modules
from app.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class Channel:
    """Discord Channel model with typed fields."""
    id: str
    name: str
    type: int
    guild_id: Optional[str] = None
    topic: Optional[str] = None
    nsfw: bool = False
    last_message_id: Optional[str] = None
    position: Optional[int] = None
    parent_id: Optional[str] = None
    permission_overwrites: List[Dict[str, Any]] = field(default_factory=list)
    rate_limit_per_user: Optional[int] = None
    created_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Channel":
        """Create Channel from Discord API response."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", ""),
            type=data.get("type", 0),
            guild_id=data.get("guild_id"),
            topic=data.get("topic"),
            nsfw=data.get("nsfw", False),
            last_message_id=data.get("last_message_id"),
            position=data.get("position"),
            parent_id=data.get("parent_id"),
            permission_overwrites=data.get("permission_overwrites", []),
            rate_limit_per_user=data.get("rate_limit_per_user"),
            created_at=data.get("created_at"),
        )


@dataclass
class Message:
    """Discord Message model with typed fields."""
    id: str
    channel_id: str
    author: Dict[str, Any]
    content: str
    timestamp: str
    edited_timestamp: Optional[str] = None
    tts: bool = False
    mention_everyone: bool = False
    mentions: List[Dict[str, Any]] = field(default_factory=list)
    mention_roles: List[str] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    embeds: List[Dict[str, Any]] = field(default_factory=list)
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    nonce: Optional[str] = None
    pinned: bool = False
    webhook_id: Optional[str] = None
    type: int = 0
    flags: Optional[int] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], channel_id: str) -> "Message":
        """Create Message from Discord API response."""
        return cls(
            id=str(data.get("id", "")),
            channel_id=channel_id,
            author=data.get("author", {}),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
            edited_timestamp=data.get("edited_timestamp"),
            tts=data.get("tts", False),
            mention_everyone=data.get("mention_everyone", False),
            mentions=data.get("mentions", []),
            mention_roles=data.get("mention_roles", []),
            attachments=data.get("attachments", []),
            embeds=data.get("embeds", []),
            reactions=data.get("reactions", []),
            nonce=data.get("nonce"),
            pinned=data.get("pinned", False),
            webhook_id=data.get("webhook_id"),
            type=data.get("type", 0),
            flags=data.get("flags"),
        )


# =============================================================================
# Custom Exceptions
# =============================================================================

class DiscordAPIError(Exception):
    """Base exception for Discord API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data or {}


class DiscordRateLimitError(DiscordAPIError):
    """Exception raised when rate limited by Discord API."""
    
    def __init__(self, retry_after: float, response_data: Optional[Dict] = None):
        super().__init__(
            message=f"Rate limited by Discord API. Retry after {retry_after:.1f}s",
            status_code=429,
            response_data=response_data
        )
        self.retry_after = retry_after


class DiscordNotFoundError(DiscordAPIError):
    """Exception raised when a Discord resource is not found."""
    
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            message=f"{resource} not found: {resource_id}",
            status_code=404
        )


class DiscordAuthError(DiscordAPIError):
    """Exception raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed. Check your token."):
        super().__init__(message=message, status_code=401)


class DiscordServerError(DiscordAPIError):
    """Exception raised when Discord server returns 5xx error."""
    
    def __init__(self, status_code: int, response_data: Optional[Dict] = None):
        super().__init__(
            message=f"Discord server error: {status_code}",
            status_code=status_code,
            response_data=response_data
        )


# =============================================================================
# Discord Client
# =============================================================================

class DiscordClient:
    """
    Typed async Discord API client with rate limit handling.
    
    Provides typed methods for interacting with Discord's API v9.
    Handles rate limiting, timeouts, and proper error propagation.
    
    Attributes:
        token: Discord bot or user token for authentication
        timeout: Request timeout in seconds (default: 15)
        max_retries: Maximum number of retry attempts for failed requests
    """
    
    BASE_URL = "https://discord.com/api/v9"
    
    def __init__(
        self,
        token: str,
        timeout: float = 15.0,
        max_retries: int = 5,
        retry_delay: float = 3.0,
        correlation_id: Optional[str] = None
    ):
        """
        Initialize the Discord client.
        
        Args:
            token: Discord bot or user token
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for transient errors
            retry_delay: Base delay between retries in seconds
            correlation_id: Optional correlation ID for request tracing
        """
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.correlation_id = correlation_id or str(uuid.uuid4())
        
        # Headers for all requests
        self.headers = {
            "Authorization": token,
            "User-Agent": "DiscordExporter/1.0",
            "Content-Type": "application/json"
        }
        
        # Create async HTTP client
        self._client: Optional[httpx.AsyncClient] = None
        
        logger.info(
            "DiscordClient initialized",
            extra={
                "correlation_id": self.correlation_id,
                "timeout": timeout,
                "max_retries": max_retries
            }
        )
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("DiscordClient closed", extra={"correlation_id": self.correlation_id})
    
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """
        Make an HTTP request with retry logic and rate limit handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            **kwargs: Additional arguments to pass to httpx request
            
        Returns:
            Response object
            
        Raises:
            DiscordRateLimitError: When rate limited
            DiscordAuthError: When authentication fails
            DiscordNotFoundError: When resource not found
            DiscordServerError: When Discord returns 5xx
            DiscordAPIError: For other API errors
        """
        client = await self._get_client()
        
        for attempt in range(self.max_retries):
            try:
                response = await client.request(method, url, **kwargs)
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = float(response.json().get("retry_after", 5))
                    logger.warning(
                        f"Rate limited. Waiting {retry_after:.1f}s before retry",
                        extra={
                            "correlation_id": self.correlation_id,
                            "attempt": attempt + 1,
                            "retry_after": retry_after
                        }
                    )
                    import asyncio
                    await asyncio.sleep(retry_after + 0.5)  # Add small buffer
                    continue
                
                # Handle authentication errors
                if response.status_code == 401:
                    logger.error(
                        "Authentication failed",
                        extra={"correlation_id": self.correlation_id}
                    )
                    raise DiscordAuthError()
                
                # Handle not found
                if response.status_code == 404:
                    raise DiscordNotFoundError("Resource", url)
                
                # Handle server errors with retry
                if response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        f"Server error {response.status_code}. Retry {attempt + 1}/{self.max_retries}",
                        extra={"correlation_id": self.correlation_id}
                    )
                    import asyncio
                    await asyncio.sleep(self.retry_delay)
                    continue
                
                # Handle other errors
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                    except Exception:
                        error_data = {}
                    
                    raise DiscordAPIError(
                        message=error_data.get("message", f"HTTP {response.status_code}"),
                        status_code=response.status_code,
                        response_data=error_data
                    )
                
                return response
                
            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{self.max_retries}): {str(e)}",
                    extra={"correlation_id": self.correlation_id}
                )
                if attempt == self.max_retries - 1:
                    raise
                import asyncio
                await asyncio.sleep(self.retry_delay)
        
        raise DiscordAPIError("Failed to complete request after multiple attempts")
    
    async def get_channel(self, channel_id: str) -> Channel:
        """
        Fetch channel information.
        
        Args:
            channel_id: The Discord channel ID
            
        Returns:
            Channel object with typed fields
            
        Raises:
            DiscordNotFoundError: If channel not found
            DiscordAuthError: If authentication fails
            DiscordAPIError: For other API errors
        """
        url = f"{self.BASE_URL}/channels/{channel_id}"
        
        logger.info(
            f"Fetching channel {channel_id}",
            extra={"correlation_id": self.correlation_id, "channel_id": channel_id}
        )
        
        response = await self._request("GET", url)
        data = response.json()
        
        channel = Channel.from_dict(data)
        
        logger.info(
            f"Channel fetched: {channel.name}",
            extra={"correlation_id": self.correlation_id, "channel_id": channel_id, "channel_name": channel.name}
        )
        
        return channel
    
    async def get_messages(
        self,
        channel_id: str,
        limit: int = 100,
        before: Optional[str] = None,
        after: Optional[str] = None
    ) -> List[Message]:
        """
        Fetch messages from a channel.
        
        Args:
            channel_id: The Discord channel ID
            limit: Number of messages to fetch (max 100 per Discord API)
            before: Message ID to get messages before this ID
            after: Message ID to get messages after this ID
            
        Returns:
            List of Message objects
            
        Raises:
            DiscordNotFoundError: If channel not found
            DiscordAuthError: If authentication fails
            DiscordAPIError: For other API errors
        """
        url = f"{self.BASE_URL}/channels/{channel_id}/messages"
        
        params: Dict[str, Any] = {
            "limit": min(limit, 100)  # Discord's max limit is 100
        }
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        
        logger.info(
            f"Fetching messages from channel {channel_id}",
            extra={
                "correlation_id": self.correlation_id,
                "channel_id": channel_id,
                "limit": params["limit"],
                "has_before": bool(before),
                "has_after": bool(after)
            }
        )
        
        response = await self._request("GET", url, params=params)
        data = response.json()
        
        messages = [Message.from_dict(msg, channel_id) for msg in data]
        
        logger.info(
            f"Fetched {len(messages)} messages",
            extra={
                "correlation_id": self.correlation_id,
                "channel_id": channel_id,
                "message_count": len(messages)
            }
        )
        
        return messages
    
    async def get_message(self, channel_id: str, message_id: str) -> Message:
        """
        Fetch a single message by ID.
        
        Args:
            channel_id: The Discord channel ID
            message_id: The Discord message ID
            
        Returns:
            Message object
            
        Raises:
            DiscordNotFoundError: If message not found
            DiscordAuthError: If authentication fails
            DiscordAPIError: For other API errors
        """
        url = f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}"
        
        logger.info(
            f"Fetching message {message_id} from channel {channel_id}",
            extra={
                "correlation_id": self.correlation_id,
                "channel_id": channel_id,
                "message_id": message_id
            }
        )
        
        response = await self._request("GET", url)
        data = response.json()
        
        return Message.from_dict(data, channel_id)


# =============================================================================
# Sync Wrapper (for backward compatibility)
# =============================================================================

class SyncDiscordClient:
    """
    Synchronous wrapper around DiscordClient for sync code.
    
    This class provides the same interface as DiscordClient but
    runs all operations synchronously.
    """
    
    def __init__(
        self,
        token: str,
        timeout: float = 15.0,
        max_retries: int = 5,
        retry_delay: float = 3.0,
        correlation_id: Optional[str] = None
    ):
        self._async_client = DiscordClient(
            token=token,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            correlation_id=correlation_id
        )
    
    def get_channel(self, channel_id: str) -> Channel:
        """Synchronously fetch channel information."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_client.get_channel(channel_id)
        )
    
    def get_messages(
        self,
        channel_id: str,
        limit: int = 100,
        before: Optional[str] = None,
        after: Optional[str] = None
    ) -> List[Message]:
        """Synchronously fetch messages from a channel."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._async_client.get_messages(channel_id, limit, before, after)
        )
    
    def close(self) -> None:
        """Close the client."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, schedule close
                loop.create_task(self._async_client.close())
            else:
                loop.run_until_complete(self._async_client.close())
        except RuntimeError:
            # No event loop, create new one
            asyncio.run(self._async_client.close())
