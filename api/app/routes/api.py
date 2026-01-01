from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from typing import List, Dict, Any, Optional
import os
import json
import time
import logging
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
    ExportFormat
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", response_model=HealthCheckResponse, status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint"""
    return HealthCheckResponse()

@router.get("/info", response_model=dict, status_code=status.HTTP_200_OK)
async def get_api_info():
    """Get API information and available endpoints"""
    return {
        "service": "Discord Exporter API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Check API health status",
            "GET /info": "Get API information",
            "POST /export": "Export Discord channel messages",
            "GET /channel/{channel_id}": "Get channel information",
            "GET /exports": "List all exported files",
            "GET /exports/{filename}": "Download an exported file"
        },
        "documentation": "/docs"
    }

@router.post(
    "/export",
    response_model=ExportResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    }
)
async def export_messages(export_request: ExportRequest):
    """
    Export messages from a Discord channel
    
    This endpoint exports messages from a Discord channel to various formats.
    The export is performed asynchronously, and the response includes a job ID
    that can be used to check the export status.
    """
    try:
        # Create exporter instance
        exporter = DiscordExporter(token=export_request.token)
        
        # Ensure output directory exists
        output_dir = os.path.abspath(export_request.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        
        # Convert export formats to boolean flags
        export_flags = {
            'export_json_raw': ExportFormat.JSON in export_request.export_formats,
            'export_jsonl': ExportFormat.JSONL in export_request.export_formats,
            'export_txt': ExportFormat.TXT in export_request.export_formats,
            'export_csv': ExportFormat.CSV in export_request.export_formats,
            'export_html': ExportFormat.HTML in export_request.export_formats
        }
        
        # Start export
        result = exporter.export_channel(
            channel_id=export_request.channel_id,
            output_dir=output_dir,
            limit=export_request.limit,
            save_frequency=export_request.save_frequency,
            start_date=export_request.start_date,
            end_date=export_request.end_date,
            format_discord_kit=export_request.format_discord_kit,
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
