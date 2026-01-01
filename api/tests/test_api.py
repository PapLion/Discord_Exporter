"""
Tests for the API endpoints.
"""
import pytest
from fastapi import status
from app.models.schemas import ExportRequest

def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"

def test_api_info(client):
    """Test the API info endpoint."""
    response = client.get("/api/v1/info")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "service" in data
    assert "version" in data
    assert "endpoints" in data

def test_export_missing_token(client):
    """Test export endpoint with missing token."""
    response = client.post(
        "/api/v1/export",
        json={"channel_id": "123"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_export_missing_channel_id(client):
    """Test export endpoint with missing channel ID."""
    response = client.post(
        "/api/v1/export",
        json={"token": "test_token"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

@pytest.mark.skip(reason="Requires valid Discord token")
def test_export_channel_integration(client):
    """Test the export channel endpoint with valid data."""
    test_data = ExportRequest(
        token="YOUR_DISCORD_TOKEN",
        channel_id="YOUR_CHANNEL_ID",
        limit=10,
        export_formats=["json", "txt"]
    )
    
    response = client.post(
        "/api/v1/export",
        json=test_data.dict()
    )
    
    assert response.status_code == status.HTTP_200_OK
    result = response.json()
    assert result["status"] == "success"
    assert result["message_count"] > 0
    assert len(result["exported_files"]) > 0
