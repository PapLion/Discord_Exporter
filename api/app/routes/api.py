from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from typing import List, Dict, Any, Optional
from pathlib import Path
import os
import json
import time
import logging
import psutil
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, validator
from enum import Enum
import aiohttp
import asyncio
import csv
import html
import re

from app.config import settings
from app.core.discord_exporter import DiscordExporter
from app.models.schemas import (
    ExportRequest,
    ExportResponse,
    ChannelInfoResponse,
    ErrorResponse,
    ExportFormat,
    JobStatusResponse,
    ExportResponseAsync,
    HealthCheckResponse
)
from app.services.export_service import get_export_service, ExportService

logger = logging.getLogger(__name__)
router = APIRouter()

# Feature flag for async export (can be enabled via environment variable)
ASYNC_EXPORT_ENABLED = os.getenv("ASYNC_EXPORT_ENABLED", "false").lower() == "true"

@router.get("/health", response_model=HealthCheckResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint"""
    return HealthCheckResponse()


@router.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness_probe():
    """
    Liveness probe endpoint for Kubernetes.
    
    Returns "alive" if the application is running.
    This endpoint has no dependencies - it simply confirms
    the process is alive and responding.
    """
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness_probe():
    """
    Readiness probe endpoint for Kubernetes.
    
    Checks that all dependencies are available:
    - Redis connection (if configured)
    - Export directory writable
    - Disk space available
    
    Returns "ready" if all checks pass, "degraded" if some fail.
    """
    checks = {}
    overall_status = "ready"
    
    # Check Redis connection
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url and redis_url != "":
        try:
            import redis
            r = redis.from_url(redis_url, socket_connect_timeout=2)
            r.ping()
            checks["redis"] = {"status": "ok", "message": "Connected"}
        except Exception as e:
            checks["redis"] = {"status": "error", "message": str(e)}
            overall_status = "degraded"
    else:
        checks["redis"] = {"status": "skipped", "message": "Not configured"}
    
    # Check export directory
    export_dir = settings.EXPORT_DIR
    try:
        export_path = Path(export_dir)
        if not export_path.exists():
            export_path.mkdir(parents=True, exist_ok=True)
        
        # Check if writable
        if os.access(export_path, os.W_OK):
            checks["export_dir"] = {"status": "ok", "path": str(export_path)}
        else:
            checks["export_dir"] = {"status": "error", "message": "Not writable"}
            overall_status = "degraded"
    except Exception as e:
        checks["export_dir"] = {"status": "error", "message": str(e)}
        overall_status = "degraded"
    
    # Check disk space
    try:
        stat = os.statvfs(export_dir if os.path.exists(export_dir) else ".")
        free_bytes = stat.f_bavail * stat.f_frsize
        free_mb = free_bytes / (1024 * 1024)
        free_percent = (free_bytes / (stat.f_blocks * stat.f_frsize)) * 100
        
        if free_mb < 100:
            checks["disk_space"] = {
                "status": "warning",
                "free_mb": round(free_mb, 2),
                "free_percent": round(free_percent, 2)
            }
            if overall_status == "ready":
                overall_status = "degraded"
        else:
            checks["disk_space"] = {
                "status": "ok",
                "free_mb": round(free_mb, 2),
                "free_percent": round(free_percent, 2)
            }
    except Exception as e:
        checks["disk_space"] = {"status": "error", "message": str(e)}
        overall_status = "degraded"
    
    return {
        "status": overall_status,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat()
    }


# Application start time for uptime calculation
APP_START_TIME = time.time()


@router.get("/metrics", status_code=status.HTTP_200_OK)
async def get_metrics():
    """
    Metrics endpoint with basic statistics.
    
    Returns:
    - Total exports completed
    - Active jobs (pending + processing)
    - Uptime in seconds
    - Memory usage (if available)
    """
    try:
        export_service = get_export_service()
        
        # Get job statistics
        all_jobs = export_service.list_exports(limit=1000)
        
        completed_count = sum(1 for j in all_jobs if j["status"] == "completed")
        active_jobs = [j for j in all_jobs if j["status"] in ("pending", "processing")]
        
        # Calculate uptime
        uptime_seconds = time.time() - APP_START_TIME
        uptime_hours = uptime_seconds / 3600
        
        # Get memory usage if available
        memory_info = {}
        try:
            process = psutil.Process()
            mem = process.memory_info()
            memory_info = {
                "rss_mb": round(mem.rss / (1024 * 1024), 2),
                "vms_mb": round(mem.vms / (1024 * 1024), 2),
                "percent": round(process.memory_percent(), 2)
            }
        except Exception:
            memory_info = {"available": False}
        
        return {
            "exports": {
                "total_completed": completed_count,
                "total_jobs": len(all_jobs)
            },
            "jobs": {
                "active": len(active_jobs),
                "pending": sum(1 for j in active_jobs if j["status"] == "pending"),
                "processing": sum(1 for j in active_jobs if j["status"] == "processing"),
                "failed": sum(1 for j in all_jobs if j["status"] == "failed"),
                "cancelled": sum(1 for j in all_jobs if j["status"] == "cancelled")
            },
            "system": {
                "uptime_seconds": round(uptime_seconds, 2),
                "uptime_hours": round(uptime_hours, 2),
                "memory": memory_info
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to get metrics",
                "details": str(e)
            }
        )


@router.get("/info", response_model=dict, status_code=status.HTTP_200_OK)
async def get_api_info():
    """Get API information and available endpoints"""
    return {
        "service": "Discord Exporter API",
        "version": "1.0.0",
        "async_enabled": ASYNC_EXPORT_ENABLED,
        "endpoints": {
            "GET /health": "Check API health status",
            "GET /info": "Get API information",
            "POST /export": "Export Discord channel messages",
            "GET /jobs/{job_id}": "Get job status",
            "DELETE /jobs/{job_id}": "Cancel a job",
            "GET /channel/{channel_id}": "Get channel information",
            "GET /exports": "List all exported files",
            "GET /exports/{filename}": "Download an exported file"
        },
        "documentation": "/docs"
    }


@router.post(
    "/export",
    response_model=Any,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    }
)
async def export_messages(export_request: ExportRequest):
    """
    Export messages from a Discord channel.
    
    This endpoint exports messages from a Discord channel to various formats.
    When ASYNC_EXPORT_ENABLED is true, the export is performed asynchronously
    and returns a job ID that can be used to check the export status.
    """
    try:
        # Get export service
        export_service = get_export_service()
        
        # Convert export formats to list of strings
        export_formats = [fmt.value for fmt in (export_request.export_formats or [])]
        
        # Build request data
        request_data = {
            "token": export_request.token,
            "channel_id": export_request.channel_id,
            "output_dir": export_request.output_dir or "exports",
            "limit": export_request.limit or 1000,
            "save_frequency": export_request.save_frequency or 1000,
            "start_date": export_request.start_date,
            "end_date": export_request.end_date,
            "format_discord_kit": export_request.format_discord_kit or False,
            "custom_filename": export_request.custom_filename,
            "export_formats": export_formats
        }
        
        # Check if async is enabled
        if ASYNC_EXPORT_ENABLED:
            # Start async export
            job_id = export_service.start_export(request_data)
            
            logger.info(
                f"Async export started: {job_id}",
                extra={"job_id": job_id, "channel_id": export_request.channel_id}
            )
            
            return ExportResponseAsync(
                status="accepted",
                job_id=job_id,
                message="Export job started. Use /jobs/{job_id} to check status."
            )
        
        # Synchronous export (original behavior)
        # Create exporter instance
        exporter = DiscordExporter(token=export_request.token)
        
        # Ensure output directory exists
        output_dir = os.path.abspath(export_request.output_dir or "exports")
        os.makedirs(output_dir, exist_ok=True)
        
        # Convert export formats to boolean flags
        export_flags = {
            'export_json_raw': 'json' in export_formats,
            'export_jsonl': 'jsonl' in export_formats,
            'export_txt': 'txt' in export_formats,
            'export_csv': 'csv' in export_formats,
            'export_html': 'html' in export_formats
        }
        
        # Start export
        result = exporter.export_channel(
            channel_id=export_request.channel_id,
            output_dir=output_dir,
            limit=export_request.limit or 1000,
            save_frequency=export_request.save_frequency or 1000,
            start_date=export_request.start_date,
            end_date=export_request.end_date,
            format_discord_kit=export_request.format_discord_kit or False,
            custom_filename=export_request.custom_filename,
            **export_flags
        )
        
        # Format response
        if result.get("status") == "error":
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "status": "error",
                    "error": result.get("error", "Unknown error during export"),
                    "message_count": result.get("message_count", 0),
                    "exported_files": result.get("exported_files", [])
                }
            )
        
        return ExportResponse(
            status="success",
            message=f"Successfully exported {result.get('message_count', 0)} messages",
            message_count=result.get("message_count", 0),
            exported_files=result.get("exported_files", [])
        )
        
    except Exception as e:
        logger.error(f"Export failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to export messages",
                "details": str(e)
            }
        )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={
        404: {"model": ErrorResponse}
    }
)
async def get_job_status(job_id: str):
    """
    Get the status of an export job.
    
    Args:
        job_id: The job identifier returned from POST /export
        
    Returns:
        Job status including progress and result if completed
    """
    try:
        export_service = get_export_service()
        job_status = export_service.get_export_status(job_id)
        
        if not job_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Job not found", "job_id": job_id}
            )
        
        return JobStatusResponse(
            job_id=job_status["job_id"],
            status=job_status["status"],
            progress=job_status["progress"],
            progress_message=job_status["progress_message"],
            result=job_status.get("result"),
            error=job_status.get("error"),
            created_at=datetime.fromisoformat(job_status["created_at"]),
            updated_at=datetime.fromisoformat(job_status["updated_at"])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to get job status",
                "details": str(e)
            }
        )


@router.delete(
    "/jobs/{job_id}",
    responses={
        404: {"model": ErrorResponse}
    }
)
async def cancel_job(job_id: str):
    """
    Cancel an export job.
    
    Args:
        job_id: The job identifier to cancel
        
    Returns:
        Success message
    """
    try:
        export_service = get_export_service()
        success = export_service.cancel_export(job_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Job not found or cannot be cancelled", "job_id": job_id}
            )
        
        return {
            "status": "cancelled",
            "job_id": job_id,
            "message": "Job cancelled successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to cancel job",
                "details": str(e)
            }
        )

@router.get(
    "/channel/{channel_id}",
    response_model=ChannelInfoResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    }
)
async def get_channel_info(
    channel_id: str,
    token: str = Query(..., description="Discord authentication token")
):
    """Get information about a Discord channel"""
    try:
        exporter = DiscordExporter(token=token)
        channel_info = exporter.get_channel_info(channel_id)
        
        if not channel_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found or access denied"
            )
            
        return channel_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch channel info: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to fetch channel information",
                "details": str(e)
            }
        )

@router.get("/exports", response_model=List[dict])
async def list_exports(
    output_dir: str = Query("exports", description="Directory to list exports from")
):
    """List all exported files"""
    try:
        output_path = Path(output_dir)
        
        if not output_path.exists() or not output_path.is_dir():
            return []
        
        exports = []
        for file_path in output_path.glob("*"):
            if file_path.is_file():
                stats = file_path.stat()
                exports.append({
                    "name": file_path.name,
                    "size": stats.st_size,
                    "modified": stats.st_mtime,
                    "path": str(file_path.relative_to(Path.cwd()))
                })
        
        return exports
        
    except Exception as e:
        logger.error(f"Failed to list exports: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to list exported files",
                "details": str(e)
            }
        )

@router.get("/exports/{filename:path}")
async def download_export(
    filename: str,
    output_dir: str = Query("exports", description="Directory containing the exports")
):
    """Download an exported file"""
    try:
        file_path = Path(output_dir) / filename
        
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        return FileResponse(
            file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download export: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to download file",
                "details": str(e)
            }
        )
