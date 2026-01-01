"""
Example test client for the Discord Exporter API.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

class TestDiscordExporterClient:
    """Test client for the Discord Exporter API."""
    
    def setup_method(self):
        """Set up the test client."""
        self.client = TestClient(app)
        
    def test_health_check(self):
        """Test the health check endpoint."""
        response = self.client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        
    def test_export_channel_missing_params(self):
        """Test export channel with missing parameters."""
        # Missing token
        response = self.client.post(
            "/api/v1/export",
            json={"channel_id": "123"}
        )
        assert response.status_code == 422
        
        # Missing channel_id
        response = self.client.post(
            "/api/v1/export",
            json={"token": "test_token"}
        )
        assert response.status_code == 422
    
    @pytest.mark.skip(reason="Requires valid Discord token")
    def test_export_channel(self):
        """Test exporting a channel (requires valid token)."""
        response = self.client.post(
            "/api/v1/export",
            json={
                "token": "YOUR_DISCORD_TOKEN",
                "channel_id": "YOUR_CHANNEL_ID",
                "limit": 5,
                "export_formats": ["json", "txt"]
            }
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
