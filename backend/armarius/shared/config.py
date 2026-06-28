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

    # Public URL of THIS Armarius API that agents call back into (claim/comment/
    # publish). Embedded into the invitation prompt. Set this to the externally
    # reachable origin when agents run on other machines (e.g. https://armarius.example.com).
    public_base_url: str = "http://localhost:8080"

    # Shared Artifact Store backend: "local" (filesystem) or "minio" (S3, ARCHITECTURE §7).
    artifact_store_backend: str = "local"
    artifact_store_root: str = "./artifacts_store"

    # MinIO / S3 — used when artifact_store_backend == "minio".
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "armarius"
    minio_secret_key: str = "armarius123"
    minio_bucket: str = "armarius"
    minio_secure: bool = False

    wake_max_continuation_attempts: int = 3
    run_timeout_seconds: int = 900

    # Demo seed ("Acme Web Platform" scenario). OFF by default — real users get
    # their own empty workspace on register. Set ARMARIUS_SEED_DEMO=true to repopulate
    # the demo story (e.g. for a fresh showcase instance).
    seed_demo: bool = False

    # JWT settings for user authentication
    jwt_secret: str = "change-me-in-production-use-secrets-manager"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def public_api_url(self) -> str:
        return self.public_base_url.rstrip("/")

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
