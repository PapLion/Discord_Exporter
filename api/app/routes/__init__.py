"""
API route definitions for the Discord Exporter API.

This package contains all the API endpoints and their handlers.
"""

from fastapi import APIRouter
from . import api

# Create main router
router = APIRouter()

# Include all route modules
router.include_router(api.router, tags=["api"])

__all__ = ["router"]
