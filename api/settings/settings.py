from pathlib import Path
import tomllib
from typing import Any
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from api.settings.database import DatabaseConfig
from api.settings.server import ServerConfig


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    """
    Custom settings source that loads configuration from a TOML file.
    This has lower priority than environment variables.
    """

    def __init__(self, settings_cls: type[BaseSettings], toml_file: Path | None = None):
        super().__init__(settings_cls)
        self.toml_file = toml_file or Path("config.toml")
        self.toml_data: dict[str, Any] = {}
        self._load_toml()

    def _load_toml(self) -> None:
        """Load data from TOML file."""
        if self.toml_file and self.toml_file.exists():
            with open(self.toml_file, "rb") as f:
                self.toml_data = tomllib.load(f)

    def _normalize_keys(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert keys to uppercase to match Pydantic field names."""
        normalized = {}
        for key, value in data.items():
            upper_key = key.upper()
            if isinstance(value, dict):
                normalized[upper_key] = self._normalize_keys(value)
            else:
                normalized[upper_key] = value
        return normalized

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        """Get value for a field from TOML data."""
        # Normalize the TOML data keys to uppercase
        normalized_data = self._normalize_keys(self.toml_data)
        field_value = normalized_data.get(field_name)
        return field_value, field_name, False

    def __call__(self) -> dict[str, Any]:
        """Return all values from TOML file with normalized keys."""
        return self._normalize_keys(self.toml_data)


class Settings(BaseSettings):
    APP_NAME: str = Field(default="Rental", description="Application name")
    APP_VERSION: str = Field(default="0.1.0", description="Application version")
    DEBUG: bool = Field(default=False, description="Debug mode")
    ENVIRONMENT: str = Field(
        default="DEV", description="Environment of the application"
    )
    SERVER: ServerConfig = Field(
        default_factory=ServerConfig, description="Server configuration settings"
    )
    POSTGRES: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="PostgreSQL database settings"
    )
    
    model_config = SettingsConfigDict(
        env_prefix="RENTAL_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Customize settings sources priority.
        Priority (highest to lowest):
        1. Environment variables
        2. .env file
        3. TOML file
        4. Default values
        """
        return (
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, Path("config.toml")),
            init_settings,
        )


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get the global settings instance.
    Creates a new instance if one doesn't exist.

    Args:
        config_file: Path to the configuration TOML file

    Returns:
        Settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> None:
    """Reload the global settings instance."""
    global _settings
    if _settings is not None:
        _settings = Settings()