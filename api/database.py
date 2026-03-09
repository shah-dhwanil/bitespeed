"""
Database connection pool manager using asyncpg.

This module provides a connection pool manager for PostgreSQL using asyncpg.
It handles pool creation, lifecycle management, and provides connection context managers.
"""

import asyncio
from contextlib import asynccontextmanager
from json import dumps, loads
from typing import Optional

import asyncpg
import structlog

from api.settings.database import DatabaseConfig

logger = structlog.get_logger(__name__)


class DatabasePool:
    """
    Manages asyncpg connection pool for PostgreSQL database.

    This class handles the creation, lifecycle, and access to the asyncpg
    connection pool with proper resource management.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Initialize database pool manager.

        Args:
            config: Database configuration settings
        """
        self.config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._is_initialized = False

    async def init_connection(self, connection: asyncpg.Connection):
        await connection.set_type_codec(
            "json",
            encoder=dumps,
            decoder=loads,
            schema="pg_catalog",
        )

    async def connect(self) -> None:
        """
        Create and initialize the connection pool.

        Raises:
            Exception: If pool creation fails
        """
        if self._is_initialized:
            logger.warning("Database pool already initialized")
            return

        try:
            logger.info(
                "Creating database connection pool",
                min_size=self.config.POOL_MIN_SIZE,
                max_size=self.config.POOL_MAX_SIZE,
            )

            self._pool = await asyncpg.create_pool(
                host=self.config.HOST,
                port=self.config.PORT,
                database=self.config.NAME,
                user=self.config.USER,
                password=self.config.PASSWORD,
                min_size=self.config.POOL_MIN_SIZE,
                max_size=self.config.POOL_MAX_SIZE,
                max_inactive_connection_lifetime=self.config.POOL_MAX_INACTIVE_CONNECTION_LIFETIME,
                timeout=self.config.POOL_TIMEOUT,
                command_timeout=60.0,
                init=self.init_connection,
            )

            self._is_initialized = True
            logger.info("Database connection pool created successfully")

        except Exception as e:
            logger.error("Failed to create database connection pool", error=str(e))
            raise

    async def disconnect(self) -> None:
        """
        Close the connection pool and cleanup resources.
        """
        if not self._is_initialized or self._pool is None:
            logger.warning("Database pool not initialized or already closed")
            return

        try:
            logger.info("Closing database connection pool")
            await asyncio.wait_for(self._pool.close(), timeout=10)
            self._pool = None
            self._is_initialized = False
            logger.info("Database connection pool closed successfully")

        except Exception as e:
            logger.error("Error closing database connection pool", error=str(e))
            raise

    @asynccontextmanager
    async def acquire(self):
        """
        Acquire a connection from the pool.

        Yields:
            asyncpg.Connection: Database connection

        Raises:
            RuntimeError: If pool is not initialized
            Exception: If connection acquisition fails
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )

        connection = None
        try:
            connection = await self._pool.acquire(timeout=self.config.POOL_TIMEOUT)
            logger.debug("Connection acquired from pool")
            yield connection
        except asyncpg.TooManyConnectionsError as e:
            logger.error("Too many connections in pool", error=str(e))
            raise
        except asyncpg.PostgresConnectionError as e:
            logger.error("Pool connection error", error=str(e))
            raise
        except Exception as e:
            logger.error("Unexpected error acquiring connection", error=str(e))
            raise
        finally:
            if connection is not None:
                try:
                    await self._pool.release(connection)
                    logger.debug("Connection released back to pool")
                except Exception as e:
                    logger.error("Error releasing connection", error=str(e))

    @asynccontextmanager
    async def transaction(self):
        """
        Acquire a connection and start a transaction.

        Yields:
            asyncpg.Connection: Database connection with active transaction

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )

        async with self.acquire() as connection:
            async with connection.transaction():
                logger.debug("Transaction started")
                try:
                    yield connection
                    logger.debug("Transaction completed successfully")
                except Exception as e:
                    logger.error("Transaction failed, rolling back", error=str(e))
                    raise

    async def execute(self, query: str, *args, timeout: Optional[float] = None) -> str:
        """
        Execute a SQL command (INSERT, UPDATE, DELETE, etc.).

        Args:
            query: SQL query string
            *args: Query parameters
            timeout: Query timeout in seconds

        Returns:
            Status of the command execution

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )

        async with self.acquire() as connection:
            return await connection.execute(query, *args, timeout=timeout)

    async def fetch(
        self, query: str, *args, timeout: Optional[float] = None
    ) -> list[asyncpg.Record]:
        """
        Fetch all rows matching the query.

        Args:
            query: SQL query string
            *args: Query parameters
            timeout: Query timeout in seconds

        Returns:
            List of records

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )

        async with self.acquire() as connection:
            return await connection.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args, timeout: Optional[float] = None
    ) -> Optional[asyncpg.Record]:
        """
        Fetch a single row matching the query.

        Args:
            query: SQL query string
            *args: Query parameters
            timeout: Query timeout in seconds

        Returns:
            Single record or None

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )
        async with self.acquire() as connection:
            return await connection.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self, query: str, *args, column: int = 0, timeout: Optional[float] = None
    ):
        """
        Fetch a single value from the query result.

        Args:
            query: SQL query string
            *args: Query parameters
            column: Column index to fetch (default: 0)
            timeout: Query timeout in seconds

        Returns:
            Single value

        Raises:
            RuntimeError: If pool is not initialized
        """
        if not self._is_initialized or self._pool is None:
            raise RuntimeError(
                "Database pool is not initialized. Call connect() first."
            )

        async with self.acquire() as connection:
            return await connection.fetchval(
                query, *args, column=column, timeout=timeout
            )

    @property
    def is_initialized(self) -> bool:
        """Check if the pool is initialized."""
        return self._is_initialized

    async def get_pool_stats(self) -> dict:
        """
        Get current pool statistics.

        Returns:
            Dictionary with pool statistics
        """
        if not self._is_initialized or self._pool is None:
            return {
                "initialized": False,
                "size": 0,
                "free": 0,
            }

        return {
            "initialized": True,
            "size": self._pool.get_size(),
            "free": self._pool.get_idle_size(),
            "min_size": self._pool.get_min_size(),
            "max_size": self._pool.get_max_size(),
        }


# Global database pool instance
_db_pool: Optional[DatabasePool] = None


def get_db_pool() -> DatabasePool:
    """
    Get the global database pool instance.

    Returns:
        DatabasePool instance

    Raises:
        RuntimeError: If pool has not been initialized
    """
    if _db_pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db_pool() first.")
    return _db_pool


def init_db_pool(config: DatabaseConfig) -> DatabasePool:
    """
    Initialize the global database pool instance.

    Args:
        config: Database configuration

    Returns:
        Initialized DatabasePool instance
    """
    global _db_pool
    if _db_pool is None:
        _db_pool = DatabasePool(config)
        logger.info("Database pool instance created")
    return _db_pool


async def close_db_pool() -> None:
    """Close the global database pool instance."""
    global _db_pool
    if _db_pool is not None:
        await _db_pool.disconnect()
        _db_pool = None
        logger.info("Database pool instance closed and cleaned up")