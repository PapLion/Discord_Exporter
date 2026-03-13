"""
Infrastructure module for Discord Exporter.

This module contains:
- discord_client: Typed Discord API client
- queue: Job queue abstraction
"""

from app.infrastructure.discord_client import (
    DiscordClient,
    SyncDiscordClient,
    Channel,
    Message,
    DiscordAPIError,
    DiscordRateLimitError,
    DiscordNotFoundError,
    DiscordAuthError,
    DiscordServerError
)

from app.infrastructure.queue import (
    JobQueue,
    InMemoryQueue,
    RedisQueue,
    Job,
    JobStatus,
    create_queue
)

__all__ = [
    # Discord client
    "DiscordClient",
    "SyncDiscordClient",
    "Channel",
    "Message",
    "DiscordAPIError",
    "DiscordRateLimitError",
    "DiscordNotFoundError",
    "DiscordAuthError",
    "DiscordServerError",
    # Queue
    "JobQueue",
    "InMemoryQueue",
    "RedisQueue",
    "Job",
    "JobStatus",
    "create_queue"
]
