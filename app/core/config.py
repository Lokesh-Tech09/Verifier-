"""
Application configuration.

Settings are loaded from environment variables / a `.env` file, with sane
defaults for local development. See `.env.example` for all available knobs.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "DrawTally API"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # Upload
    UPLOAD_MAX_SIZE: int = 50 * 1024 * 1024  # 50MB
    UPLOAD_TIMEOUT: int = 30  # seconds
    TEMP_DIR: Path = Path("/tmp/drawtally")
    TEMP_FILE_TTL: int = 300  # 5 minutes cleanup

    # OCR
    OCR_DPI: int = 300
    OCR_LANG: str = "eng"
    OCR_PSM: int = 6  # Page segmentation mode
    OCR_CONFIDENCE_THRESHOLD: float = 0.6

    # Matching
    FUZZY_MATCH_THRESHOLD: int = 75  # 0-100

    # Security
    CORS_ORIGINS: list[str] = ["*"]  # Restrict in production
    RATE_LIMIT_PER_MINUTE: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "text"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# Make sure the temp directory exists at import time.
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
