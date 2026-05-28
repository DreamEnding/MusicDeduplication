"""Configuration management for Music Deduplication application."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    # Backup settings
    backup_dir: str = str(Path.home() / ".music_deduper" / "backups")

    # AI settings
    ai_default_url: str = ""
    ai_default_model: str = "gpt-4o-mini"

    # Logging settings
    log_level: str = "INFO"
    log_file: str = "music_deduper.log"

    # Security settings
    allowed_origins: list[str] = [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # Scanning settings
    max_scan_timeout: int = 300  # seconds
    max_execute_timeout: int = 600  # seconds

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_prefix": "MUSIC_DEDUP_",
    }


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings."""
    return settings
