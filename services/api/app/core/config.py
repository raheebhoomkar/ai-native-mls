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
    # Uploaded media; see app/modules/media/storage.py. "local" keeps files under media_root
    # (one server only). "s3" uses any S3-compatible bucket; credentials come from the usual
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY variables, never from this file.
    media_storage: Literal["local", "s3"] = "local"
    media_root: Path = REPO_ROOT / "var" / "media"
    media_s3_bucket: str | None = None
    # For S3-compatible services other than AWS (Cloudflare R2, MinIO, ...).
    media_s3_endpoint_url: str | None = None
    media_s3_region: str | None = None
    # Removed media is kept this long before its files are deleted from storage.
    media_retention_days: int = Field(default=7, ge=0, le=3650)
    media_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    # Signs short-lived media download URLs. Required in production.
    media_signing_key: SecretStr | None = Field(default=None, min_length=32)
    # AI vision provider; see app/modules/ai/providers.py. No key: the labelled demo adapter.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash"
    # Gemini takes 15-40 s per call; overloaded models answer 503 only after about 80 s.
    ai_timeout_seconds: float = Field(default=90, ge=5, le=600)
    # Geocoder; see app/modules/geo/geocoder.py. "demo" knows city centres only.
    geocoder: Literal["demo", "nominatim"] = "demo"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim's usage policy asks for an identifying User-Agent; operators add a contact here.
    geocoder_user_agent: str = "ai-native-mls/0.1"
    # Embedder for semantic search; see app/modules/search/embedder.py. Not switched on by the
    # key alone: a new embedder re-indexes every listing and sends listing text to Google.
    embedder: Literal["demo", "gemini"] = "demo"
    gemini_embedding_model: str = "gemini-embedding-001"
    # Where listing vectors live; see app/modules/search/vector_store.py.
    vector_store: Literal["postgres", "qdrant"] = "postgres"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    # Lets a scheduler such as Vercel Cron run background jobs over HTTP: GET /ops/run-jobs
    # with "Authorization: Bearer <CRON_SECRET>". Unset: that route answers 404.
    cron_secret: SecretStr | None = Field(default=None, min_length=16)

    @field_validator("gemini_api_key", "qdrant_api_key", "cron_secret", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return value or None

    @model_validator(mode="after")
    def _check_media(self) -> Self:
        if self.environment == "production" and self.media_signing_key is None:
            raise ValueError("MEDIA_SIGNING_KEY must be set in production.")
        if self.media_storage == "s3" and not self.media_s3_bucket:
            raise ValueError("MEDIA_S3_BUCKET must be set when MEDIA_STORAGE is s3.")
        if self.embedder == "gemini" and self.gemini_api_key is None:
            raise ValueError("GEMINI_API_KEY must be set when EMBEDDER is gemini.")
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
