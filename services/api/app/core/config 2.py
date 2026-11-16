from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Validated at startup: a missing or malformed value stops the process."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: PostgresDsn
    session_ttl_hours: int = Field(default=12, ge=1, le=720)
    # Directory holding the built web app. When set, the API also serves it (single container).
    web_dist_dir: Path | None = None
    # Demo data at start-up. In production both must be set; see app/seed.py.
    seed_demo_data: bool = False
    seed_password: SecretStr | None = Field(default=None, min_length=12)

    @field_validator("database_url", mode="before")
    @classmethod
    def _use_psycopg3(cls, value: object) -> object:
        """Hosts hand out `postgres://` or `postgresql://`; SQLAlchemy needs the driver named."""
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg://" + value[len(prefix) :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
