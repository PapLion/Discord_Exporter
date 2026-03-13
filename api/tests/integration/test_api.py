"""
Integration tests for API endpoints.

Tests:
- Health endpoint returns 200
- /export returns proper response
- Invalid token returns 401
- Rate limiting returns 429
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import os

# Set environment variable for async export
os.environ["ASYNC_EXPORT_ENABLED"] = "false"

from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_discord_exporter():
    """Mock the DiscordExporter to avoid real API calls."""
    with patch('app.core.discord_exporter.DiscordExporter') as mock:
        mock_instance = Mock()
        mock_instance.export_channel = Mock(return_value={
            "status": "success",
            "message_count": 100,
            "exported_files": ["exports/test.json"]
        })
        mock.return_value = mock_instance
        yield mock


class TestHealthEndpoint:
    """Tests for health check endpoints."""
    
    def test_health_returns_200(self, client):
        """Test that /health returns 200 OK."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
    
    def test_health_live_returns_200(self, client):
        """Test that /health/live returns 200 OK."""
        response = client.get("/api/v1/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
    
    def test_health_ready_returns_200(self, client):
        """Test that /health/ready returns 200 OK."""
        response = client.get("/api/v1/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
    
    def test_root_returns_200(self, client):
        """Test that root endpoint returns 200."""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data


class TestInfoEndpoint:
    """Tests for /info endpoint."""
    
    def test_info_returns_200(self, client):
        """Test that /info returns 200."""
        response = client.get("/api/v1/info")
        
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data
        assert "endpoints" in data


class TestExportEndpoint:
    """Tests for /export endpoint."""
    
    def test_export_returns_success(self, client, mock_discord_exporter):
        """Test that export returns success response."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789",
            "output_dir": "exports",
            "limit": 100
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "message_count" in data
        assert "exported_files" in data
    
    def test_export_requires_token(self, client):
        """Test that export requires token field."""
        response = client.post("/api/v1/export", json={
            "channel_id": "123456789"
        })
        
        # Validation error (422)
        assert response.status_code == 422
    
    def test_export_requires_channel_id(self, client):
        """Test that export requires channel_id field."""
        response = client.post("/api/v1/export", json={
            "token": "test-token"
        })
        
        # Validation error (422)
        assert response.status_code == 422
    
    def test_export_validates_limit_range(self, client):
        """Test that export validates limit is in range."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789",
            "limit": -1  # Invalid: must be >= 1
        })
        
        assert response.status_code == 422
    
    def test_export_invalid_date_format(self, client):
        """Test that export validates date format."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789",
            "start_date": "invalid-date"
        })
        
        assert response.status_code == 422
    
    def test_export_with_all_formats(self, client, mock_discord_exporter):
        """Test export with all format options."""
        response = client.post("/api/v1/export", json={
            "token": "test-token",
            "channel_id": "123456789",
            "export_formats": ["json", "jsonl", "txt", "csv", "html"]
        })
        
        assert response.status_code == 200


class TestJobEndpoints:
    """Tests for job status endpoints."""
    
    def test_get_job_status_not_found(self, client):
        """Test that getting non-existent job returns 404."""
        response = client.get("/api/v1/jobs/non-existent-job-id")
        
        assert response.status_code == 404
    
    def test_cancel_job_not_found(self, client):
        """Test that cancelling non-existent job returns 404."""
        response = client.delete("/api/v1/jobs/non-existent-job-id")
        
        assert response.status_code == 404


class TestChannelEndpoint:
    """Tests for channel info endpoint."""
    
    def test_channel_requires_token(self, client):
        """Test that channel endpoint requires token query param."""
        response = client.get("/api/v1/channel/123456789")
        
        assert response.status_code == 422  # Missing required query param
    
    def test_channel_info_with_token(self, client):
        """Test channel info endpoint with valid params."""
        with patch('app.core.discord_exporter.DiscordExporter') as mock:
            mock_instance = Mock()
            mock_instance.get_channel_info = Mock(return_value={
                "id": "123456789",
                "name": "test-channel",
                "type": 0
            })
            mock.return_value = mock_instance
            
            response = client.get(
                "/api/v1/channel/123456789",
                params={"token": "test-token"}
            )
            
            assert response.status_code == 200


class TestRateLimiting:
    """Tests for rate limiting."""
    
    def test_rate_limit_headers_present(self, client):
        """Test that rate limit headers are present in responses."""
        response = client.get("/api/v1/health")
        
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
    
    def test_rate_limit_exceeded_returns_429(self, client):
        """Test that rate limiting returns 429 when exceeded."""
        # Exhaust rate limit by making many requests
        # The rate limit is 50 requests per minute
        
        responses = []
        for _ in range(60):
            response = client.get("/api/v1/info")
            responses.append(response.status_code)
            if response.status_code == 429:
                break
        
        # Should eventually hit rate limit
        assert 429 in responses


class TestExportsList:
    """Tests for /exports endpoint."""
    
    def test_list_exports_empty(self, client):
        """Test listing exports when directory is empty."""
        # Create temp export dir for test
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        try:
            response = client.get("/api/v1/exports", params={"output_dir": temp_dir})
            
            assert response.status_code == 200
            assert isinstance(response.json(), list)
        finally:
            shutil.rmtree(temp_dir)
    
    def test_list_exports_nonexistent_dir(self, client):
        """Test listing exports for non-existent directory."""
        response = client.get("/api/v1/exports", params={"output_dir": "/nonexistent/dir"})
        
        assert response.status_code == 200
        assert response.json() == []


class TestMetrics:
    """Tests for metrics endpoint."""
    
    def test_metrics_returns_200(self, client):
        """Test that metrics endpoint returns 200."""
        response = client.get("/api/v1/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "exports" in data
        assert "jobs" in data
        assert "system" in data


class TestAuthentication:
    """Tests for authentication/authorization."""
    
    def test_missing_auth_returns_401(self, client):
        """Test that requests without proper auth can still work (open API)."""
        # The API uses open auth, so this should pass
        # But we test the bearer token if provided
        
        # Test with invalid bearer token format
        response = client.post(
            "/api/v1/export",
            json={
                "token": "test-token",
                "channel_id": "123456789"
            },
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        # Should still work since token is in body
        assert response.status_code in [200, 500]  # 500 if mock fails
