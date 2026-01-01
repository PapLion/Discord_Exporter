"""
Discord Exporter API Application

This module initializes the FastAPI application and sets up the API routes.
"""

# Import the main FastAPI application
from .main import app

# This allows us to import the app directly from the app package
__all__ = ["app"]
