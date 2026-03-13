"""
Job queue abstraction with in-memory and Redis implementations.

This module provides:
- Abstract JobQueue base class
- InMemoryQueue implementation (synchronous)
- RedisQueue implementation (asynchronous, optional)
- Job and JobStatus dataclasses
- Result storage with TTL support
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
import json
import logging
import asyncio
import threading

# Import from local modules
from app.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Enums and Data Classes
# =============================================================================

class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """
    Represents a job in the queue.
    
    Attributes:
        id: Unique job identifier
        status: Current job status
        data: Job input data (dict)
        result: Job result data (set when completed)
        error: Error message if failed
        created_at: Job creation timestamp
        updated_at: Last update timestamp
        progress: Progress percentage (0-100)
        progress_message: Human-readable progress message
    """
    id: str
    status: JobStatus
    data: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    progress: int = 0
    progress_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization."""
        return {
            "id": self.id,
            "status": self.status.value,
            "data": self.data,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "progress_message": self.progress_message
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create Job from dictionary."""
        return cls(
            id=data["id"],
            status=JobStatus(data["status"]),
            data=data["data"],
            result=data.get("result"),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            progress=data.get("progress", 0),
            progress_message=data.get("progress_message", "")
        )


# =============================================================================
# Abstract Base Class
# =============================================================================

class JobQueue(ABC):
    """
    Abstract job queue base class.
    
    Defines the interface for job queue implementations.
    Subclasses must implement all abstract methods.
    """
    
    @abstractmethod
    def enqueue(self, job_id: str, data: Dict[str, Any]) -> bool:
        """
        Add a job to the queue.
        
        Args:
            job_id: Unique job identifier
            data: Job input data
            
        Returns:
            True if job was enqueued successfully
        """
        pass
    
    @abstractmethod
    def dequeue(self) -> Optional[Job]:
        """
        Get the next job from the queue.
        
        Returns:
            Job object if available, None otherwise
        """
        pass
    
    @abstractmethod
    def get_status(self, job_id: str) -> Optional[JobStatus]:
        """
        Get the status of a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobStatus if job exists, None otherwise
        """
        pass
    
    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Get the full job object.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job object if exists, None otherwise
        """
        pass
    
    @abstractmethod
    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[int] = None,
        progress_message: Optional[str] = None
    ) -> bool:
        """
        Update job status and result.
        
        Args:
            job_id: Job identifier
            status: New status
            result: Job result data (for completed jobs)
            error: Error message (for failed jobs)
            progress: Progress percentage (0-100)
            progress_message: Human-readable progress message
            
        Returns:
            True if update was successful
        """
        pass
    
    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """
        Cancel a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was cancelled successfully
        """
        pass
    
    @abstractmethod
    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 100) -> List[Job]:
        """
        List jobs with optional status filter.
        
        Args:
            status: Filter by job status
            limit: Maximum number of jobs to return
            
        Returns:
            List of Job objects
        """
        pass
    
    @abstractmethod
    def cleanup(self, ttl_hours: int = 24) -> int:
        """
        Remove expired jobs.
        
        Args:
            ttl_hours: Time-to-live in hours
            
        Returns:
            Number of jobs removed
        """
        pass


# =============================================================================
# In-Memory Implementation
# =============================================================================

class InMemoryQueue(JobQueue):
    """
    In-memory job queue implementation (synchronous).
    
    This implementation is suitable for single-instance deployments
    or development/testing purposes. Jobs are stored in memory and
    will be lost on application restart.
    
    Thread-safe using a lock.
    """
    
    def __init__(self, max_size: int = 10000):
        """
        Initialize the in-memory queue.
        
        Args:
            max_size: Maximum number of jobs to store
        """
        self._jobs: Dict[str, Job] = {}
        self._queue: List[str] = []  # List of job IDs
        self._lock = threading.RLock()
        self._max_size = max_size
        
        logger.info(f"InMemoryQueue initialized with max_size={max_size}")
    
    def enqueue(self, job_id: str, data: Dict[str, Any]) -> bool:
        """Add a job to the queue."""
        with self._lock:
            # Check if queue is full
            if len(self._jobs) >= self._max_size:
                logger.warning(f"Queue is full ({self._max_size} jobs)")
                return False
            
            # Check if job already exists
            if job_id in self._jobs:
                logger.warning(f"Job {job_id} already exists")
                return False
            
            # Create new job
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                data=data
            )
            
            self._jobs[job_id] = job
            self._queue.append(job_id)
            
            logger.info(f"Job {job_id} enqueued", extra={"job_id": job_id})
            return True
    
    def dequeue(self) -> Optional[Job]:
        """Get the next job from the queue."""
        with self._lock:
            # Find next pending job
            for i, job_id in enumerate(self._queue):
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.PENDING:
                    # Update status to processing
                    job.status = JobStatus.PROCESSING
                    job.updated_at = datetime.utcnow()
                    self._queue.pop(i)
                    self._queue.append(job_id)  # Re-add to end for processing
                    
                    logger.info(
                        f"Job {job_id} dequeued",
                        extra={"job_id": job_id}
                    )
                    return job
            
            return None
    
    def get_status(self, job_id: str) -> Optional[JobStatus]:
        """Get the status of a job."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.status if job else None
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get the full job object."""
        with self._lock:
            return self._jobs.get(job_id)
    
    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[int] = None,
        progress_message: Optional[str] = None
    ) -> bool:
        """Update job status and result."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                logger.warning(f"Job {job_id} not found")
                return False
            
            job.status = status
            job.updated_at = datetime.utcnow()
            
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if progress is not None:
                job.progress = progress
            if progress_message is not None:
                job.progress_message = progress_message
            
            logger.info(
                f"Job {job_id} status updated to {status.value}",
                extra={"job_id": job_id, "status": status.value}
            )
            return True
    
    def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                logger.warning(f"Job {job_id} not found")
                return False
            
            # Can only cancel pending or processing jobs
            if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
                job.status = JobStatus.CANCELLED
                job.updated_at = datetime.utcnow()
                
                # Remove from queue
                if job_id in self._queue:
                    self._queue.remove(job_id)
                
                logger.info(f"Job {job_id} cancelled", extra={"job_id": job_id})
                return True
            
            logger.warning(
                f"Cannot cancel job {job_id} with status {job.status.value}",
                extra={"job_id": job_id, "status": job.status.value}
            )
            return False
    
    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 100) -> List[Job]:
        """List jobs with optional status filter."""
        with self._lock:
            jobs = list(self._jobs.values())
            
            if status:
                jobs = [j for j in jobs if j.status == status]
            
            # Sort by created_at descending
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            
            return jobs[:limit]
    
    def cleanup(self, ttl_hours: int = 24) -> int:
        """Remove expired jobs."""
        with self._lock:
            cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)
            
            # Find completed/failed/cancelled jobs older than cutoff
            expired = [
                job_id for job_id, job in self._jobs.items()
                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
                and job.updated_at < cutoff
            ]
            
            # Remove expired jobs
            for job_id in expired:
                del self._jobs[job_id]
                if job_id in self._queue:
                    self._queue.remove(job_id)
            
            if expired:
                logger.info(f"Cleaned up {len(expired)} expired jobs")
            
            return len(expired)


# =============================================================================
# Redis Implementation (Optional)
# =============================================================================

class RedisQueue(JobQueue):
    """
    Redis-based job queue implementation (asynchronous).
    
    This implementation is suitable for production deployments
    with multiple worker instances. Requires Redis connection.
    
    Note: This is a stub implementation that requires redis-py
    to be installed and configured.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "jobqueue:",
        ttl_hours: int = 24
    ):
        """
        Initialize the Redis queue.
        
        Args:
            redis_url: Redis connection URL
            prefix: Key prefix for all queue keys
            ttl_hours: Default TTL for job results
        """
        self._redis_url = redis_url
        self._prefix = prefix
        self._ttl = timedelta(hours=ttl_hours)
        self._redis: Any = None
        
        logger.info(f"RedisQueue initialized with url={redis_url}")
    
    def _get_redis(self):
        """Get or create Redis connection."""
        if self._redis is None:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(self._redis_url)
            except ImportError:
                raise ImportError(
                    "redis package is required for RedisQueue. "
                    "Install with: pip install redis"
                )
        return self._redis
    
    async def _init_async(self) -> None:
        """Initialize async connection."""
        self._redis = await self._get_redis()
    
    def enqueue(self, job_id: str, data: Dict[str, Any]) -> bool:
        """Add a job to the queue (async wrapper)."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_enqueue(job_id, data)
        )
    
    async def _async_enqueue(self, job_id: str, data: Dict[str, Any]) -> bool:
        """Add a job to the queue."""
        redis = self._get_redis()
        
        try:
            job = Job(
                id=job_id,
                status=JobStatus.PENDING,
                data=data
            )
            
            # Store job data
            job_key = f"{self._prefix}job:{job_id}"
            await redis.set(
                job_key,
                json.dumps(job.to_dict()),
                ex=int(self._ttl.total_seconds())
            )
            
            # Add to pending queue
            queue_key = f"{self._prefix}pending"
            await redis.rpush(queue_key, job_id)
            
            logger.info(f"Job {job_id} enqueued to Redis")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {str(e)}")
            return False
    
    def dequeue(self) -> Optional[Job]:
        """Get the next job from the queue (async wrapper)."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_dequeue()
        )
    
    async def _async_dequeue(self) -> Optional[Job]:
        """Get the next job from the queue."""
        redis = self._get_redis()
        
        try:
            queue_key = f"{self._prefix}pending"
            
            # Try to get a job from the queue
            job_id = await redis.lpop(queue_key)
            
            if not job_id:
                return None
            
            job_id = job_id.decode() if isinstance(job_id, bytes) else job_id
            
            # Get job data
            job_key = f"{self._prefix}job:{job_id}"
            job_data = await redis.get(job_key)
            
            if not job_data:
                return None
            
            job = Job.from_dict(json.loads(job_data))
            
            # Update status to processing
            job.status = JobStatus.PROCESSING
            job.updated_at = datetime.utcnow()
            
            await redis.set(
                job_key,
                json.dumps(job.to_dict()),
                ex=int(self._ttl.total_seconds())
            )
            
            # Re-add to processing queue
            processing_key = f"{self._prefix}processing"
            await redis.rpush(processing_key, job_id)
            
            logger.info(f"Job {job_id} dequeued from Redis")
            return job
            
        except Exception as e:
            logger.error(f"Failed to dequeue job: {str(e)}")
            return None
    
    def get_status(self, job_id: str) -> Optional[JobStatus]:
        """Get the status of a job."""
        job = self.get_job(job_id)
        return job.status if job else None
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get the full job object."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_get_job(job_id)
        )
    
    async def _async_get_job(self, job_id: str) -> Optional[Job]:
        """Get the full job object."""
        redis = self._get_redis()
        
        try:
            job_key = f"{self._prefix}job:{job_id}"
            job_data = await redis.get(job_key)
            
            if not job_data:
                return None
            
            return Job.from_dict(json.loads(job_data))
            
        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {str(e)}")
            return None
    
    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[int] = None,
        progress_message: Optional[str] = None
    ) -> bool:
        """Update job status and result."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_update_status(job_id, status, result, error, progress, progress_message)
        )
    
    async def _async_update_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        progress: Optional[int] = None,
        progress_message: Optional[str] = None
    ) -> bool:
        """Update job status and result."""
        redis = self._get_redis()
        
        try:
            job = await self._async_get_job(job_id)
            if not job:
                return False
            
            job.status = status
            job.updated_at = datetime.utcnow()
            
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if progress is not None:
                job.progress = progress
            if progress_message is not None:
                job.progress_message = progress_message
            
            # Store updated job
            job_key = f"{self._prefix}job:{job_id}"
            await redis.set(
                job_key,
                json.dumps(job.to_dict()),
                ex=int(self._ttl.total_seconds())
            )
            
            # Remove from processing queue if completed/failed
            if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                processing_key = f"{self._prefix}processing"
                await redis.lrem(processing_key, 0, job_id)
            
            logger.info(f"Job {job_id} status updated to {status.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update job {job_id}: {str(e)}")
            return False
    
    def cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_cancel(job_id)
        )
    
    async def _async_cancel(self, job_id: str) -> bool:
        """Cancel a job."""
        job = await self._async_get_job(job_id)
        
        if not job or job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
            return False
        
        return await self._async_update_status(job_id, JobStatus.CANCELLED)
    
    def list_jobs(self, status: Optional[JobStatus] = None, limit: int = 100) -> List[Job]:
        """List jobs with optional status filter."""
        # This would require SCAN operation - simplified implementation
        logger.warning("RedisQueue.list_jobs is not fully implemented")
        return []
    
    def cleanup(self, ttl_hours: int = 24) -> int:
        """Remove expired jobs (Redis handles TTL automatically)."""
        # Redis automatically handles expiration via TTL
        return 0


# =============================================================================
# Factory Function
# =============================================================================

def create_queue(
    backend: str = "memory",
    **kwargs
) -> JobQueue:
    """
    Create a job queue instance.
    
    Args:
        backend: Queue backend ("memory" or "redis")
        **kwargs: Additional arguments for the queue
        
    Returns:
        JobQueue implementation
        
    Example:
        # In-memory queue
        queue = create_queue("memory")
        
        # Redis queue
        queue = create_queue("redis", redis_url="redis://localhost:6379/0")
    """
    if backend == "memory":
        return InMemoryQueue(**kwargs)
    elif backend == "redis":
        return RedisQueue(**kwargs)
    else:
        raise ValueError(f"Unknown queue backend: {backend}")
