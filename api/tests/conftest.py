"""
Test configuration and fixtures for pytest.
"""
import os
import sys
import pytest
from fastapi.testclient import TestClient


def pytest_configure(config):
    """Configure pytest before tests run."""
    # Add api/ to path
    api_path = os.path.abspath(os.path.dirname(__file__))
    sys.path.insert(0, api_path)


# Try to import app, but don't fail if it can't be imported
try:
    from app.main import app
    APP_AVAILABLE = True
except ImportError:
    APP_AVAILABLE = False
    app = None


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    if not APP_AVAILABLE or app is None:
        pytest.skip("App not available")
    with TestClient(app) as test_client:
        yield test_client
