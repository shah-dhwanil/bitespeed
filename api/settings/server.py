"""
Server configuration settings.

This module contains all server-related configuration including
FastAPI settings, CORS, and server host/port configurations.
"""

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ServerConfig(BaseSettings):
    """
    Server configuration for FastAPI application.

    Contains settings for host, port, CORS, and other server-specific configurations.
    """

    # Server settings
    HOST: str = Field(
        default="0.0.0.0",
        description="Server host address",
    )
    PORT: int = Field(
        default=8000,
        description="Server port",
    )
    WORKERS: int = Field(
        default=1,
        description="Number of worker processes",
    )
    RELOAD: bool = Field(
        default=False,
        description="Enable auto-reload on code changes",
    )
    # CORS settings
    CORS_ENABLED: bool = Field(
        default=True,
        description="Enable CORS middleware",
    )
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins",
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(
        default=True,
        description="Allow credentials in CORS requests",
    )
    CORS_ALLOW_METHODS: Annotated[list[str], NoDecode] = Field(
        default=["*"],
        description="Allowed HTTP methods for CORS",
    )
    CORS_ALLOW_HEADERS: Annotated[list[str], NoDecode] = Field(
        default=["*"],
        description="Allowed headers for CORS",
    )

    # Request settings
    MAX_REQUEST_SIZE: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum request body size in bytes",
    )
    REQUEST_TIMEOUT: int = Field(
        default=60,
        description="Request timeout in seconds",
    )

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = Field(
        default=False,
        description="Enable rate limiting",
    )
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        description="Rate limit per minute per IP",
    )

    model_config = SettingsConfigDict(case_sensitive=False, extra="forbid")

    @field_validator("PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number is in valid range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("WORKERS")
    @classmethod
    def validate_workers(cls, v: int) -> int:
        """Validate number of workers is positive."""
        if v < 1:
            raise ValueError("Workers must be at least 1")
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("CORS_ALLOW_METHODS", mode="before")
    @classmethod
    def parse_cors_methods(cls, v):
        """Parse CORS methods from string or list."""
        if isinstance(v, str):
            return [method.strip() for method in v.split(",")]
        return v

    @field_validator("CORS_ALLOW_HEADERS", mode="before")
    @classmethod
    def parse_cors_headers(cls, v):
        """Parse CORS headers from string or list."""
        if isinstance(v, str):
            return [header.strip() for header in v.split(",")]
        return v