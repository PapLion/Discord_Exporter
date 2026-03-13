"""
Main FastAPI application module
"""
import uuid
import os
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.routes import api as api_routes
from app.config import settings

# Import structured logger and rate limiter
from .utils.logger import get_logger, get_request_logger
from .utils.rate_limiter import RateLimiterMiddleware

# Configure logging with structured logger
logger = get_logger(__name__)

# Application start time for uptime calculation
APP_START_TIME = time.time()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts or generates a correlation ID for each request.
    
    - Extracts X-Correlation-ID from request headers if present
    - Generates a new UUID if not provided
    - Adds correlation_id to request state for access in route handlers
    - Adds correlation_id to response headers
    """
    
    async def dispatch(self, request: Request, call_next):
        # Extract correlation ID from header or generate new one
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Add correlation ID to request state for access in handlers
        request.state.correlation_id = correlation_id
        
        # Get request-scoped logger
        request_logger = get_request_logger(correlation_id)
        
        # Log incoming request
        request_logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_host": request.client.host if request.client else None,
            }
        )
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        
        # Log response
        request_logger.info(
            f"Response: {request.method} {request.url.path} - {response.status_code}",
            extra={
                "status_code": response.status_code,
            }
        )
        
        return response

def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="A RESTful API for exporting Discord channel messages",
        version=settings.VERSION,
        docs_url=None,  # Disable default docs to use custom Swagger UI
        redoc_url=None,
        openapi_url=f"{settings.API_PREFIX}/openapi.json"
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add correlation ID middleware (after CORS)
    app.add_middleware(CorrelationMiddleware)
    
    # Add rate limiting middleware (after correlation)
    # Configure: 50 requests per minute per token/IP
    app.add_middleware(
        RateLimiterMiddleware,
        capacity=50,
        refill_rate=50 / 60  # ~0.83 requests per second
    )
    
    # Include API routes
    app.include_router(api_routes.router, prefix=settings.API_PREFIX)
    
    # Startup event handler
    @app.on_event("startup")
    async def startup_event():
        """Initialize application on startup"""
        logger.info(
            f"Starting {settings.PROJECT_NAME} v{settings.VERSION}",
            extra={
                "version": settings.VERSION,
                "export_dir": settings.EXPORT_DIR,
                "debug": settings.DEBUG
            }
        )
        
        # Create export directory if it doesn't exist
        export_dir = os.path.abspath(settings.EXPORT_DIR)
        try:
            os.makedirs(export_dir, exist_ok=True)
            logger.info(f"Export directory ready: {export_dir}")
        except Exception as e:
            logger.error(f"Failed to create export directory: {e}")
        
        # Initialize export service
        from app.services.export_service import get_export_service
        export_service = get_export_service()
        logger.info("Export service initialized")
        
        # Log startup complete
        logger.info("Application startup complete")
    
    # Shutdown event handler
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup resources on shutdown"""
        logger.info("Shutting down application...")
        
        # Export service cleanup
        from app.services.export_service import get_export_service
        try:
            export_service = get_export_service()
            if hasattr(export_service, 'cleanup'):
                removed = export_service.cleanup()
                logger.info(f"Cleaned up {removed} expired jobs")
        except Exception as e:
            logger.error(f"Error during export service cleanup: {e}")
        
        logger.info("Application shutdown complete")
    
    # Custom exception handlers
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle request validation errors"""
        correlation_id = getattr(request.state, 'correlation_id', 'unknown')
        request_logger = get_request_logger(correlation_id)
        request_logger.warning(
            f"Validation error: {exc.errors()}",
            extra={
                "errors": exc.errors(),
                "body": exc.body,
            }
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Validation Error",
                "details": exc.errors(),
                "body": exc.body
            },
        )
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all other exceptions"""
        correlation_id = getattr(request.state, 'correlation_id', 'unknown')
        request_logger = get_request_logger(correlation_id)
        request_logger.error(
            f"Unhandled exception: {str(exc)}",
            exc_info=True
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "details": str(exc)
            },
        )
    
    # Custom Swagger UI
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=f"{settings.API_PREFIX}/openapi.json",
            title=f"{settings.PROJECT_NAME} - Swagger UI",
            oauth2_redirect_url=None,
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui-bundle.js",
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@3/swagger-ui.css",
        )
    
    # Custom OpenAPI schema
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        
        # Add security schemes
        openapi_schema["components"]["securitySchemes"] = {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Discord token in the format 'Bearer {token}'"
            }
        }
        
        # Add security to all endpoints
        for path in openapi_schema.get("paths", {}).values():
            for method in path.values():
                if method.get("security") is None:
                    method["security"] = [{"bearerAuth": []}]
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    app.openapi = custom_openapi
    
    # Root endpoint
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": f"Welcome to {settings.PROJECT_NAME} API",
            "version": settings.VERSION,
            "docs": "/docs",
            "openapi": f"{settings.API_PREFIX}/openapi.json"
        }
    
    return app

# Create the FastAPI application
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
