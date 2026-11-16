from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Validated at startup: a missing or malformed value stops the process."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: PostgresDsn
    session_ttl_hours: int = Field(default=12, ge=1, le=720)


@lru_cache
def get_settings() -> Settings:
    return Settings()
