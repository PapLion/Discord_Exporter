"""
Tests for the DiscordExporter class with proper mocks.
"""
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, ANY
from app.core.discord_exporter import DiscordExporter

@pytest.fixture
def mock_session():
    """Create a mock session with proper responses."""
    with patch('requests.Session') as mock_session:
        # Mock for get_channel_info
        channel_response = MagicMock()
        channel_response.status_code = 200
        channel_response.json.return_value = {
            "id": "1234567890",
            "name": "test-channel",
            "type": 0,
            "guild_id": "9876543210",
            "topic": "Test Channel Topic",
            "nsfw": False,
            "last_message_id": "123456789012345678"
        }
        
        # Mock for fetch_messages
        messages_response = MagicMock()
        messages_response.status_code = 200
        messages_response.json.return_value = [
            {
                "id": "123456789012345678",
                "channel_id": "1234567890",
                "author": {
                    "id": "987654321098765432",
                    "username": "testuser",
                    "discriminator": "1234",
                    "avatar": "a_abc123"
                },
                "content": "Test message content",
                "timestamp": "2023-01-01T12:00:00+00:00",
                "edited_timestamp": None,
                "tts": False,
                "mention_everyone": False,
                "mentions": [],
                "mention_roles": [],
                "attachments": [],
                "embeds": [],
                "pinned": False,
                "type": 0
            }
        ]
        
        # Configure the session to return different responses based on URL
        def get_side_effect(url, *args, **kwargs):
            if 'channels/1234567890' in url and '/messages' not in url:
                return channel_response
            elif 'messages' in url:
                return messages_response
            return MagicMock(status_code=404)
            
        mock_session.return_value.get.side_effect = get_side_effect
        yield mock_session

def test_discord_exporter_init():
    """Test DiscordExporter initialization."""
    token = "test_token_123"
    exporter = DiscordExporter(token)
    
    assert exporter.token == token
    assert "Authorization" in exporter.headers
    assert exporter.headers["Authorization"] == token
    assert exporter.base_url == "https://discord.com/api/v9"
    assert exporter.max_retries == 5
    assert exporter.retry_delay == 3

def test_get_channel_info_success(mock_session):
    """Test successful channel info retrieval."""
    exporter = DiscordExporter("test_token")
    channel_info = exporter.get_channel_info("1234567890")
    
    assert channel_info["id"] == "1234567890"
    assert channel_info["name"] == "test-channel"
    assert channel_info["type"] == 0
    mock_session.return_value.get.assert_called_once_with(
        "https://discord.com/api/v9/channels/1234567890",
        timeout=15
    )

def test_fetch_messages_success(mock_session):
    """Test successful message fetching."""
    exporter = DiscordExporter("test_token")
    messages = exporter.fetch_messages("1234567890", limit=1)
    
    assert len(messages) == 1
    assert messages[0]["id"] == "123456789012345678"
    assert messages[0]["content"] == "Test message content"
    mock_session.return_value.get.assert_called_with(
        "https://discord.com/api/v9/channels/1234567890/messages",
        params={"limit": 1},
        timeout=15
    )

def test_export_channel_success(mock_session, tmp_path):
    """Test successful channel export."""
    exporter = DiscordExporter("test_token")
    output_dir = tmp_path / "exports"
    
    result = exporter.export_channel(
        channel_id="1234567890",
        output_dir=str(output_dir),
        limit=1,
        export_json_raw=True,
        export_txt=True,
        export_csv=True,
        export_html=True
    )
    
    assert result["status"] == "success"
    assert result["message_count"] == 1
    assert len(result["exported_files"]) >= 1  # At least one export file
    
    # Verify files were created
    json_file = output_dir / "discord_export_test-channel_*.json"
    assert json_file.parent.exists()
    
    # Verify the export contains the test message
    if json_file.exists():
        with open(json_file, 'r') as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["content"] == "Test message content"

def test_rate_limit_handling():
    """Test rate limit handling with retries."""
    with patch('requests.Session') as mock_session:
        # First response is rate limited, second is successful
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.json.return_value = {"retry_after": 1}
        
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = [{"id": "123", "content": "test"}]
        
        mock_session.return_value.get.side_effect = [
            rate_limit_response,
            success_response
        ]
        
        exporter = DiscordExporter("test_token")
        messages = exporter.fetch_messages("1234567890", limit=1)
        
        assert len(messages) == 1
        assert messages[0]["content"] == "test"
        assert mock_session.return_value.get.call_count == 2

def test_error_handling():
    """Test error handling for failed requests."""
    with patch('requests.Session') as mock_session:
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"
        mock_session.return_value.get.return_value = error_response
        
        exporter = DiscordExporter("test_token")
        
        with pytest.raises(Exception) as exc_info:
            exporter.get_channel_info("1234567890")
        
        assert "No se pudo conectar después de varios intentos" in str(exc_info.value)
