from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class DatabaseConfig(BaseSettings):
    HOST: str = Field(
        default="localhost",
        description="Database host address",
    )
    PORT: int = Field(
        default=5432,
        description="Database port",
    )
    NAME: str = Field(
        default="gaatha_salesforce",
        description="Database name",
    )
    USER: str = Field(
        default="postgres",
        description="Database user",
    )
    PASSWORD: str = Field(
        default="",
        description="Database password",
    )
    POOL_MIN_SIZE: int = Field(
        default=1,
        description="Minimum number of connections in the pool",
    )
    POOL_MAX_SIZE: int = Field(
        default=10,
        description="Maximum number of connections in the pool",
    )
    POOL_MAX_INACTIVE_CONNECTION_LIFETIME: float = Field(
        default=300.0,
        description="Maximum inactive connection lifetime in seconds",
    )
    POOL_TIMEOUT: float = Field(
        default=10.0,
        description="Timeout for acquiring connection from pool in seconds",
    )
    model_config = SettingsConfigDict(case_sensitive=False, extra="forbid")  # noqa: F821

    @field_validator("POOL_MIN_SIZE")  # noqa: F821
    @classmethod
    def validate_pool_min_size(cls, v: int) -> int:
        """Validate minimum pool size is positive."""
        if v < 1:
            raise ValueError("Pool minimum size must be at least 1")
        return v

    @field_validator("POOL_MAX_SIZE")
    @classmethod
    def validate_pool_max_size(cls, v: int) -> int:
        """Validate maximum pool size is positive."""
        if v < 1:
            raise ValueError("Pool maximum size must be at least 1")
        return v

    def get_database_url(self, driver: str = "postgresql+asyncpg") -> str:
        """
        Generate database URL from configuration.

        Args:
            driver: Database driver (default: postgresql+asyncpg for asyncpg)

        Returns:
            Database URL string
        """
        return (
            f"{driver}://{self.USER}:{self.PASSWORD}@"
            f"{self.HOST}:{self.PORT}/{self.NAME}"
        )

    @property
    def dsn(self) -> str:
        """Get PostgreSQL DSN string."""
        return (
            f"postgresql://{self.USER}:{self.PASSWORD}@"
            f"{self.HOST}:{self.PORT}/{self.NAME}"
        )