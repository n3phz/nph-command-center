from pathlib import Path
from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    app_name: str = Field(default="arr-control")
    app_version: str = Field(default="0.1.0")
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # Data directory
    data_dir: Path = Field(default=Path("/tmp/arr-control"))
    
    # Database
    database_url: str = Field(default="sqlite:////tmp/arr-control/arr-control.db")

    # Polling
    poll_interval_seconds: int = Field(default=30)
    poll_timeout_seconds: int = Field(default=10)

    # Sonarr Configuration
    sonarr_url: str = Field(default="http://localhost:8989")
    sonarr_api_key: str = Field(default="")
    sonarr_timeout_seconds: int = Field(default=10)
    sonarr_verify_tls: bool = Field(default=True)

    # Radarr Configuration
    radarr_url: str = Field(default="http://localhost:7878")
    radarr_api_key: str = Field(default="")
    radarr_timeout_seconds: int = Field(default=10)
    radarr_verify_tls: bool = Field(default=True)

    # qBittorrent Configuration
    qbittorrent_url: str = Field(default="http://localhost:8080")
    qbittorrent_username: str = Field(default="admin")
    qbittorrent_password: str = Field(default="adminadmin")
    qbittorrent_timeout_seconds: int = Field(default=10)
    qbittorrent_verify_tls: bool = Field(default=True)

    # Prowlarr Configuration
    prowlarr_url: str = Field(default="http://localhost:9696")
    prowlarr_api_key: str = Field(default="")
    prowlarr_timeout_seconds: int = Field(default=10)
    prowlarr_verify_tls: bool = Field(default=True)

    # Guardarr Configuration
    guardarr_url: str = Field(default="http://localhost:8000")
    guardarr_api_key: str = Field(default="")
    guardarr_timeout_seconds: int = Field(default=10)
    guardarr_verify_tls: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("data_dir", mode="before")
    @classmethod
    def ensure_absolute_path(cls, v: Any) -> Path:
        if isinstance(v, str):
            return Path(v).resolve()
        return v


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings