"""
FastAPI application instance with lifespan management.

This module creates the FastAPI application with proper configuration,
middleware, and lifespan management for database and logging setup.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from api.exceptions.handler import register_exception_handlers
from api.lifespan import lifespan
from api.middleware import ContextMiddleware, LoggingMiddleware, RequestIDMiddleware
from api.models.errors import HTTPException
from api.settings import get_settings

# Load settings
settings = get_settings()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,  # Attach lifespan context manager
        responses={
            500: {"model": HTTPException, "description": "Internal Server Error"},
            404: {"model": HTTPException, "description": "Resource Not Found"},
            400: {"model": HTTPException, "description": "Bad Request"},
            409: {"model": HTTPException, "description": "Conflict"},
            403: {"model": HTTPException, "description": "Forbidden"},
            422: {"model": HTTPException, "description": "Unprocessable Entity"},
        },
    )
    register_exception_handlers(app)
    # Configure CORS middleware
    if settings.SERVER.CORS_ENABLED:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.SERVER.CORS_ORIGINS,
            allow_credentials=settings.SERVER.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.SERVER.CORS_ALLOW_METHODS,
            allow_headers=settings.SERVER.CORS_ALLOW_HEADERS,
        )
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(ContextMiddleware)
    app.add_middleware(RequestIDMiddleware)


    return app


# Create the application instance
app: FastAPI = create_app()

@app.get("/scalar", include_in_schema=False)
async def custom_swagger_ui():
    """Custom Swagger UI endpoint."""
    template = """
    <!doctype html>
<html>
  <head>
    <title>API Reference</title>
    <meta charset="utf-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""
    return HTMLResponse(content=template, status_code=200)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    from api.database import get_db_pool

    try:
        db_pool = get_db_pool()
        pool_stats = await db_pool.get_pool_stats()

        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "status": "healthy",
            "database": {
                "connected": pool_stats["initialized"],
                "pool_size": pool_stats.get("size", 0),
                "pool_free": pool_stats.get("free", 0),
            },
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }