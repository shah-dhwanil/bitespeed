"""
FastAPI lifespan context manager for application startup and shutdown.

This module provides a lifespan context manager that handles:
- Logging configuration
- Database connection pool initialization and cleanup
- DynamoDB agent memory table provisioning
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from api.sentry import setup_sentry
from api.settings import get_settings
from api.database import close_db_pool, init_db_pool
from api.logging import setup_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Handles application startup and shutdown events:
    - Startup: Setup logging and initialize database connection pool
    - Shutdown: Close database connections and cleanup resources

    Args:
        app: FastAPI application instance

    Yields:
        None
    """
    # Startup: Initialize resources
    logger.debug("Application startup initiated")
    try:
        setup_sentry()
        # Setup logging configuration
        settings = get_settings()
        setup_logging(settings)

        # Initialize database connection pool
        db_pool = init_db_pool(settings.POSTGRES)
        await db_pool.connect()

        # Log database pool statistics
        pool_stats = await db_pool.get_pool_stats()
        logger.debug(
            "Database connection pool initialized",
            **pool_stats,
        )
        logger.debug("Application startup completed successfully")

    except Exception as e:
        logger.error(
            "Failed to initialize application",
            error=str(e),
            exc_info=True,
        )
        raise

    # Application is running - yield control to FastAPI
    yield

    # Shutdown: Cleanup resources
    logger.debug("Application shutdown initiated")

    try:
        # Close database connection pool
        await close_db_pool()
        logger.debug("Database connection pool closed")

        logger.debug("Application shutdown completed successfully")

    except Exception as e:
        logger.error(
            "Error during application shutdown",
            error=str(e),
            exc_info=True,
        )
        raise