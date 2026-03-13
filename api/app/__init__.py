"""
Discord Exporter API Application

This module initializes the FastAPI application and sets up the API routes.
"""

# Import the main FastAPI application lazily to avoid import errors when deps missing
def __getattr__(name):
    if name == "app":
        from .main import app
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["app"]
