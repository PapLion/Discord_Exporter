"""
Async export orchestration service.

This module provides:
- ExportService: Main service for orchestrating exports
- Background job processing
- Progress tracking
- Result storage with 24-hour TTL
"""

import os
import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

# Import from local modules
from app.config import settings
from app.infrastructure.queue import JobQueue, InMemoryQueue, Job, JobStatus
from app.infrastructure.discord_client import DiscordClient
from app.core.discord_exporter import DiscordExporter
from app.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Export Service
# =============================================================================

class ExportService:
    """
    Async export orchestration service.
    
    Manages export jobs using a job queue backend.
    Supports background processing, progress tracking,
    and result storage with 24-hour TTL.
    
    Attributes:
        queue: Job queue backend
        exporter_class: Exporter class to use for exports
    """
    
    RESULT_TTL_HOURS = 24
    
    def __init__(
        self,
        queue: Optional[JobQueue] = None,
        exporter_class: type = DiscordExporter
    ):
        """
        Initialize the export service.
        
        Args:
            queue: Job queue backend (defaults to InMemoryQueue)
            exporter_class: Exporter class to use for exports
        """
        self._queue = queue or InMemoryQueue()
        self._exporter_class = exporter_class
        self._running_tasks: Dict[str, asyncio.Task] = {}
        
        logger.info("ExportService initialized")
    
    @property
    def queue(self) -> JobQueue:
        """Get the job queue."""
        return self._queue
    
    def start_export(
        self,
        request_data: Dict[str, Any]
    ) -> str:
        """
        Start an export job.
        
        Args:
            request_data: Export request data containing:
                - token: Discord authentication token
                - channel_id: Discord channel ID
                - output_dir: Output directory
                - limit: Max messages to export
                - start_date: Start date filter
                - end_date: End date filter
                - export_formats: List of formats to export
                - format_discord_kit: Format for DiscordKit
                - custom_filename: Custom filename
                - save_frequency: Save progress every N messages
                
        Returns:
            Job ID for tracking the export
            
        Example:
            job_id = export_service.start_export({
                "token": "...",
                "channel_id": "123456789",
                "output_dir": "exports",
                "limit": 1000
            })
        """
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Enqueue the job
        self._queue.enqueue(job_id, request_data)
        
        logger.info(
            f"Export job {job_id} started",
            extra={
                "job_id": job_id,
                "channel_id": request_data.get("channel_id")
            }
        )
        
        # Start background processing (if in async context)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule background task
                task = loop.create_task(self._process_job_async(job_id))
                self._running_tasks[job_id] = task
        except RuntimeError:
            # No event loop, process synchronously
            pass
        
        return job_id
    
    async def _process_job_async(self, job_id: str) -> None:
        """
        Process a job asynchronously.
        
        Args:
            job_id: Job identifier
        """
        try:
            # Get job data
            job = self._queue.get_job(job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return
            
            request_data = job.data
            
            # Update status to processing
            self._queue.update_status(
                job_id,
                JobStatus.PROCESSING,
                progress=0,
                progress_message="Starting export..."
            )
            
            # Create exporter
            token = request_data.get("token")
            exporter = self._exporter_class(token=token)
            
            # Extract parameters
            channel_id = request_data.get("channel_id")
            output_dir = request_data.get("output_dir", "exports")
            limit = request_data.get("limit", 1000)
            save_frequency = request_data.get("save_frequency", 1000)
            start_date = request_data.get("start_date")
            end_date = request_data.get("end_date")
            format_discord_kit = request_data.get("format_discord_kit", False)
            custom_filename = request_data.get("custom_filename")
            export_formats = request_data.get("export_formats", ["json", "jsonl", "txt", "csv", "html"])
            
            # Convert export formats to flags
            export_flags = {
                'export_json_raw': 'json' in export_formats,
                'export_jsonl': 'jsonl' in export_formats,
                'export_txt': 'txt' in export_formats,
                'export_csv': 'csv' in export_formats,
                'export_html': 'html' in export_formats
            }
            
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Run export with progress updates
            self._queue.update_status(
                job_id,
                JobStatus.PROCESSING,
                progress=10,
                progress_message="Fetching channel info..."
            )
            
            # Perform export
            result = exporter.export_channel(
                channel_id=channel_id,
                output_dir=output_dir,
                limit=limit,
                save_frequency=save_frequency,
                start_date=start_date,
                end_date=end_date,
                format_discord_kit=format_discord_kit,
                custom_filename=custom_filename,
                **export_flags
            )
            
            # Check result
            if result.get("status") == "error":
                self._queue.update_status(
                    job_id,
                    JobStatus.FAILED,
                    error=result.get("error", "Unknown error"),
                    progress=100,
                    progress_message="Export failed"
                )
                logger.error(
                    f"Export job {job_id} failed: {result.get('error')}",
                    extra={"job_id": job_id}
                )
            else:
                # Include file paths in result
                result_with_files = {
                    "status": result.get("status"),
                    "message_count": result.get("message_count", 0),
                    "exported_files": result.get("exported_files", [])
                }
                
                self._queue.update_status(
                    job_id,
                    JobStatus.COMPLETED,
                    result=result_with_files,
                    progress=100,
                    progress_message=f"Export completed: {result.get('message_count', 0)} messages"
                )
                logger.info(
                    f"Export job {job_id} completed: {result.get('message_count', 0)} messages",
                    extra={"job_id": job_id}
                )
            
        except Exception as e:
            logger.error(
                f"Export job {job_id} failed with exception: {str(e)}",
                extra={"job_id": job_id},
                exc_info=True
            )
            self._queue.update_status(
                job_id,
                JobStatus.FAILED,
                error=str(e),
                progress=100,
                progress_message="Export failed"
            )
        finally:
            # Clean up task reference
            self._running_tasks.pop(job_id, None)
    
    def get_export_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of an export job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Dict containing job status, progress, and result if completed
            
        Example:
            status = export_service.get_export_status(job_id)
            # Returns:
            # {
            #     "job_id": "...",
            #     "status": "processing",
            #     "progress": 50,
            #     "progress_message": "Exporting messages...",
            #     "result": None  # Only populated when completed
            # }
        """
        job = self._queue.get_job(job_id)
        
        if not job:
            return None
        
        return {
            "job_id": job_id,
            "status": job.status.value,
            "progress": job.progress,
            "progress_message": job.progress_message,
            "result": job.result,
            "error": job.error,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat()
        }
    
    def cancel_export(self, job_id: str) -> bool:
        """
        Cancel an export job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was cancelled successfully
            
        Example:
            success = export_service.cancel_export(job_id)
        """
        # Cancel the job in queue
        success = self._queue.cancel(job_id)
        
        # Cancel running task if exists
        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            self._running_tasks.pop(job_id, None)
        
        if success:
            logger.info(f"Export job {job_id} cancelled", extra={"job_id": job_id})
        
        return success
    
    def list_exports(
        self,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List all export jobs.
        
        Args:
            status: Filter by status (pending, processing, completed, failed, cancelled)
            limit: Maximum number of jobs to return
            
        Returns:
            List of job status dictionaries
        """
        job_status = JobStatus(status) if status else None
        jobs = self._queue.list_jobs(status=job_status, limit=limit)
        
        return [
            {
                "job_id": job.id,
                "status": job.status.value,
                "progress": job.progress,
                "progress_message": job.progress_message,
                "error": job.error,
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat()
            }
            for job in jobs
        ]
    
    def cleanup(self) -> int:
        """
        Remove expired jobs (older than 24 hours).
        
        Returns:
            Number of jobs removed
        """
        removed = self._queue.cleanup(ttl_hours=self.RESULT_TTL_HOURS)
        logger.info(f"Cleaned up {removed} expired export jobs")
        return removed


# =============================================================================
# Global Service Instance
# =============================================================================

# Global export service instance
_export_service: Optional[ExportService] = None


def get_export_service() -> ExportService:
    """
    Get the global export service instance.
    
    Returns:
        ExportService singleton instance
    """
    global _export_service
    
    if _export_service is None:
        _export_service = ExportService()
    
    return _export_service


def set_export_service(service: ExportService) -> None:
    """
    Set the global export service instance.
    
    This allows for dependency injection in tests or custom configurations.
    
    Args:
        service: ExportService instance
    """
    global _export_service
    _export_service = service
