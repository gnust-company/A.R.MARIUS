"""Typed runtime configuration sourced from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"


def _parse_int_csv(raw: str) -> list[int]:
    """Parse a comma-separated list of positive ints, ignoring blanks and junk."""
    values: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value > 0:
            values.append(value)
    return values


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
    # Liveness watchdog cadence — how often the background loop advances every Marius.
    liveness_watchdog_interval_seconds: float = 30.0

    # --- Autonomous project operation (spec 001) -------------------------------
    # System-wide FLOOR for every timing threshold the safety net and the orchestrator
    # rely on. A project may override any of these per-project (see `default_thresholds`
    # on the Project entity); a field the project leaves unset falls back here.
    # Every value is a deliberate decision recorded in spec.md — do not tune blindly.

    # A run that has emitted nothing for this long is *suspected* hung.
    hang_suspect_seconds: int = 600
    # Grace window after suspicion before the run is *declared* hung and reaped.
    hang_grace_seconds: int = 120
    # How often the stall watchdog sweeps every open task looking for a missing or
    # expired push reason. Cheap query — it only compares one timestamp column.
    stall_scan_interval_seconds: float = 60.0
    # Orchestration heartbeat per project. Skips silently when nothing hangs (FR-053).
    orchestration_cadence_seconds: int = 900
    # Ceiling on how many times the cadence may wake one project's Leader in an hour
    # (FR-055). Four at the 15-minute base rhythm means a project that is genuinely on
    # fire still gets every sweep, and one that is merely noisy cannot monopolise the
    # Leader's turns.
    orchestration_wakes_per_hour: int = 4
    # How often the orchestration loop body wakes up to see which projects are due.
    # Much shorter than any project's own rhythm: the loop ticks, the project decides.
    orchestration_tick_seconds: float = 60.0
    # Hours-before-deadline marks at which a task counts as *due soon* (FR-052). A task
    # with no deadline is never due soon.
    due_soon_hours: str = "24,12,6,1"
    # Escalating reminder tiers for a patron inbox item left unanswered, in hours (FR-065).
    patron_reminder_hours: str = "8,24,72"
    # Level-1 self-recovery budget: how many times the system re-wakes the same assignee
    # for the same task before escalating to the Leader (FR-059). Distinct from
    # `wake_max_continuation_attempts`, which caps continuations *within* one run.
    level1_recovery_attempts: int = 3
    # The first gap between Level-1 re-wakes; it doubles from here (FR-060). Five minutes
    # rather than one on purpose: the stall sweep runs every minute, so a shorter gap
    # would let the sweeps outpace the ladder and burn the whole budget inside four
    # minutes — three re-wakes nobody had time to answer, then straight to the Leader.
    # A budget spent that fast is decoration.
    level1_backoff_seconds: int = 300
    # How many review rejections on one task before the Leader is pulled in to re-examine
    # the brief and the acceptance criteria (FR-042).
    rejection_round_cap: int = 3

    # Demo seed ("Acme Web Platform" scenario). OFF by default — real users get
    # their own empty workspace on register. Set ARMARIUS_SEED_DEMO=true to repopulate
    # the demo story (e.g. for a fresh showcase instance). The seed registers the demo
    # Patron below so the showcase journey is reachable end-to-end (login + own workspace).
    seed_demo: bool = False
    demo_email: str = "demo@acme.dev"
    demo_password: str = "demo1234"

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
    def due_soon_hour_marks(self) -> list[int]:
        """Due-soon marks, descending — a task crosses each one at most once."""
        return sorted(_parse_int_csv(self.due_soon_hours), reverse=True)

    @property
    def patron_reminder_hour_tiers(self) -> list[int]:
        """Reminder tiers, ascending — tier 1 fires first, then 2, then 3."""
        return sorted(_parse_int_csv(self.patron_reminder_hours))

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
