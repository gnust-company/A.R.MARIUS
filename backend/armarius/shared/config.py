"""Typed runtime configuration sourced from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings. Override via environment variables or backend/.env."""

    model_config = SettingsConfigDict(
        env_file=[str(DEFAULT_ENV_FILE), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./armarius.db"
    cors_origins: str = "*"

    artifact_store_root: str = "./artifacts_store"

    wake_max_continuation_attempts: int = 3
    run_timeout_seconds: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def artifact_store_path(self) -> Path:
        path = Path(self.artifact_store_root)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
