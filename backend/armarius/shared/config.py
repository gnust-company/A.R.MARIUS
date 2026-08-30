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

    # Public URL of the web interface a *person* opens. Distinct from `public_base_url`,
    # which is the API agents call: the machine-linking answer has to tell someone where
    # to go and press approve, and that address is the interface, not the API.
    web_base_url: str = "http://localhost:3000"

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
    # How long a machine may go without a beat before every agent on it counts as offline
    # (FR-006a). The daemon beats every 15 seconds (contracts/daemon-api.md), so this is
    # three missed beats. The window is fixed here rather than read back from whatever the
    # daemon was configured with, for a simple reason: a machine that has stopped beating
    # is exactly the machine that can no longer be asked how often it meant to.
    machine_unreachable_after_seconds: float = 45.0

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
    # How far a run of quiet sweeps may stretch the cadence, as a multiple of the base
    # rhythm (FR-055). Eight doublings is three quiet sweeps' worth of earned slack.
    orchestration_max_stretch: int = 8
    # …and the wall that stretch hits regardless. A quiet project is quiet, not finished,
    # so something must still look at it within the hour or two.
    orchestration_max_interval_seconds: int = 2 * 60 * 60
    # The floor no rhythm may go below, however much is backing up. A sweep is a handful
    # of queries, but a loop running them every few seconds is a busy-wait in costume.
    orchestration_min_interval_seconds: int = 60
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
    # Level-2 budget: how many spaced asks the Leader gets before the patron is told
    # (FR-060). Deliberately *not* the Level-1 budget, even though three is the same
    # number today: that one answers "how long do we let an agent keep trying", which a
    # project may reasonably raise to ten for agents that sleep a lot, and raising it must
    # not silently make a patron wait through ten failed calls to a Leader before hearing
    # their Leader is gone. Different question, different knob.
    level2_handover_attempts: int = 3
    # How many review rejections on one task before the Leader is pulled in to re-examine
    # the brief and the acceptance criteria (FR-042).
    rejection_round_cap: int = 3

    # --- Machines running the daemon (spec 002) --------------------------------
    # How long the short code printed by `armarius-daemon login` stays valid. Ten
    # minutes is the whole window a person has to walk from their terminal to a browser
    # and press approve; long enough to do it unhurried, short enough that a code read
    # off someone's screen is worthless by the time it is typed in (FR-001).
    daemon_link_code_ttl_seconds: int = 600
    # How often the waiting daemon should ask again. Handed to it in the answer rather
    # than compiled in, so the pace stays the server's to change.
    daemon_link_poll_interval_seconds: int = 5
    # How long a machine's token is good for once issued.
    daemon_token_ttl_days: int = 90
    # How much life has to be left before a renewal request is granted. The daemon may
    # ask at any rhythm it likes and the server answers *not yet* until the token falls
    # inside this window — FR-014d puts the decision here precisely so a machine never
    # computes its own expiry. Two weeks is comfortably longer than any plausible
    # outage, so a machine that was switched off for a fortnight still comes back to a
    # token it can renew rather than one it has to re-link.
    daemon_token_renew_within_days: int = 14

    # How long a machine keeps a run it has taken before the run goes back on the
    # shelf (FR-056a, FR-056c, research §3). One number with two jobs on purpose: it is
    # the deadline written onto the hold, and it is the life of drive #1 between the
    # moment a runtime takes the work and the moment the agent produces its first line.
    # Split in two they would drift, and a hold shorter than the drive would take work
    # back from a machine that is doing everything right.
    #
    # 120 seconds is many times the 2-5 seconds of laying out a working directory,
    # writing the skills and starting a CLI. Being generous costs nothing: each agent is
    # bound to one place (FR-007), so expiry is not about handing the work to somebody
    # else — it is about work ceasing to be *taken* by a machine that has died.
    run_claim_hold_seconds: int = 120
    # How often the sweep looks for holds that ran out. Well under the hold above, so a
    # dead machine's grip is measured in one hold plus a little, not in two.
    run_claim_reap_interval_seconds: float = 30.0

    # How much of a long event stays in the event row itself (FR-049). Over this, the whole
    # text goes to `run_event_blobs` and the row keeps an opening slice.
    #
    # Set for the read that hurts: a screen opening a run asks for every event it has, and a
    # thousand of them must still arrive quickly (SC-014). 2 KiB is enough that almost nothing
    # is ever split, and small enough that a run full of long prompts is still one page.
    #
    # Nothing to do with tool results, which are cut on the user's own machine and have no
    # second half here at all (FR-043a).
    run_event_inline_bytes: int = 2048

    # How long the full log is kept (FR-050). Counted from the event's own clock.
    #
    # Its own setting, deliberately: the working directory on a machine is cleared on the
    # machine's rhythm and for the machine's reasons — disk. This is the record of what an
    # agent did and why, which is read by people, months later, to answer a question about
    # work that was signed for. Tying the two together would make one of them wrong.
    run_trace_retention_days: int = 30
    # How often the sweep looks for a log past its keeping. Once an hour: the threshold is in
    # days, so a sweep any keener only asks the database the same question more often.
    run_trace_sweep_interval_seconds: float = 3600.0

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
