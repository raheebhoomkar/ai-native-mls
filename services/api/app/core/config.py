from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
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
    # Uploaded media. Local disk for now; see app/modules/media/storage.py.
    media_root: Path = REPO_ROOT / "var" / "media"
    media_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    # Signs short-lived media download URLs. Required in production; see `_media_key_in_production`.
    media_signing_key: SecretStr | None = Field(default=None, min_length=32)

    @model_validator(mode="after")
    def _media_key_in_production(self) -> Self:
        if self.environment == "production" and self.media_signing_key is None:
            raise ValueError("MEDIA_SIGNING_KEY must be set in production.")
        return self

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
