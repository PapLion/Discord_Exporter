from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum

class ExportFormat(str, Enum):
    JSON = "json"
    JSONL = "jsonl"
    TXT = "txt"
    CSV = "csv"
    HTML = "html"

class ExportRequest(BaseModel):
    """Request model for export endpoint"""
    token: str = Field(..., description="Discord authentication token")
    channel_id: str = Field(..., description="Discord channel ID to export")
    output_dir: Optional[str] = Field("exports", description="Output directory for exported files")
    limit: Optional[int] = Field(1000, ge=1, le=100000, description="Maximum number of messages to export")
    save_frequency: Optional[int] = Field(1000, ge=100, le=10000, description="Save progress every N messages")
    start_date: Optional[str] = Field(None, description="Only include messages after this date (ISO 8601 format)")
    end_date: Optional[str] = Field(None, description="Only include messages before this date (ISO 8601 format)")
    format_discord_kit: Optional[bool] = Field(False, description="Format output for DiscordKit")
    custom_filename: Optional[str] = Field(None, description="Custom base filename for exports")
    export_formats: Optional[List[ExportFormat]] = Field(
        ["json", "jsonl", "txt", "csv", "html"], 
        description="List of export formats to generate"
    )

    @validator('start_date', 'end_date')
    def validate_date_format(cls, v):
        if v is None:
            return v
        try:
            # Try parsing the date to validate format
            datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except ValueError:
            raise ValueError(f"Invalid date format. Expected ISO 8601 format, got {v}")

class ExportResponse(BaseModel):
    """Response model for export endpoint"""
    status: str = Field(..., description="Export status (success, error, partial)")
    message: Optional[str] = Field(None, description="Status message")
    message_count: int = Field(0, description="Number of messages exported")
    exported_files: List[str] = Field(default_factory=list, description="List of exported file paths")
    error: Optional[str] = Field(None, description="Error message if export failed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

class ChannelInfoResponse(BaseModel):
    """Response model for channel info endpoint"""
    id: str
    name: str
    type: int
    guild_id: Optional[str] = None
    topic: Optional[str] = None
    nsfw: bool = False
    last_message_id: Optional[str] = None
    message_count: Optional[int] = None
    created_at: Optional[datetime] = None

class HealthCheckResponse(BaseModel):
    """Response model for health check endpoint"""
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ErrorResponse(BaseModel):
    """Standard error response model"""
    error: str
    code: int
    details: Optional[Dict[str, Any]] = None
