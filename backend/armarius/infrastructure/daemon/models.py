"""ORM models for the on-machine daemon runtime (feature 002, data-model.md).

Six tables, all infrastructure-only. They share `Base` with the core models so a single
`create_all` / Alembic autogenerate pass sees them; `database/models.py` imports this
module at its own bottom to make that registration happen.

Constitution III: none of these concepts may surface above the adapter contract. `runs`
gets exactly one neutral column (`accepted_at`); the machine that accepted a run is
recorded here, in `run_claims`, not on the domain entity.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from armarius.infrastructure.database.models import Base


class MachineModel(Base):
    """A machine running the daemon, enrolled into exactly one workspace.

    There is deliberately no `status` column: a machine is *reachable* when
    `last_heartbeat_at` falls within three heartbeat intervals. Storing that as a column
    would be a second copy of a clock-derived truth, free to drift from the clock.
    """

    __tablename__ = "machines"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    # Only ever the hash. The token itself is shown to the daemon once, at link time.
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    daemon_version: Mapped[str] = mapped_column(String(40), default="")
    platform: Mapped[str] = mapped_column(String(20), default="")
    symlink_capable: Mapped[bool] = mapped_column(Boolean, default=False)
    # Server-side ceiling on concurrent runs. The daemon reports its free slots as advice;
    # the server takes the smaller of the two.
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkplaceModel(Base):
    """One (agent CLI present on a machine x workspace) pair — the thing that claims work.

    `not_ready_reason` holds a machine-readable code, never a sentence: the UI renders the
    sentence through i18n (Constitution VI + VII). Every not-ready branch collapses to the
    same conclusion for the layers above — the agent is offline.
    """

    __tablename__ = "workplaces"
    __table_args__ = (
        UniqueConstraint("machine_id", "cli_kind", name="uq_workplace_machine_cli"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    machine_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("machines.id"), index=True
    )
    cli_kind: Mapped[str] = mapped_column(String(40))
    cli_version: Mapped[str] = mapped_column(String(40), default="")
    protocol_family: Mapped[str] = mapped_column(String(20), default="")
    # Answers to a real capability handshake, never inferred from `cli_kind`.
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    not_ready_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DaemonLinkCodeModel(Base):
    """Single-use device-flow code that binds a machine to a workspace.

    The three `reported_*` columns hold what the daemon announced at `link/start`. They
    have to survive until approval, because the `machines` row is only created once a
    human approves the code — there is nowhere else to keep them in between.
    """

    __tablename__ = "daemon_link_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_daemon_link_code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id")
    )
    machine_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("machines.id"))
    reported_platform: Mapped[str] = mapped_column(String(20), default="")
    reported_daemon_version: Mapped[str] = mapped_column(String(40), default="")
    reported_hostname: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunClaimModel(Base):
    """Which machine currently holds a run, and until when.

    Invariant: a run is either free (`machine_id IS NULL`) or held by exactly one machine
    with a live deadline — never both. The partial index below is what makes the claim
    statement cheap; it is the only index the hot compare-and-swap path needs.
    """

    __tablename__ = "run_claims"
    __table_args__ = (
        Index(
            "ix_run_claims_unclaimed",
            "workplace_id",
            sqlite_where=text("machine_id IS NULL"),
            postgresql_where=text("machine_id IS NULL"),
        ),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id"), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    workplace_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workplaces.id"))
    machine_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("machines.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)


class AgentWorkplaceBindingModel(Base):
    """Which workplace an agent runs on. Set when the agent is created; never changed.

    Only the agent create/invite flow writes here. An agent with no row is reported
    offline — the absence has a defined meaning, so it can never be a silent failure.
    """

    __tablename__ = "agent_workplace_bindings"

    marius_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("mariuses.id"), primary_key=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    workplace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workplaces.id"), index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEventBlobModel(Base):
    """Full text of an event too large to keep inline on `run_events`.

    Carries `workspace_id` of its own, unlike `run_events`: reading the log is a hot path,
    and joining runs → project → workspace on every read just to learn the tenant is a
    cost with no return. The difference is deliberate.

    Only the kinds allowed to leave the user's machine in full may land here — the prompt
    sent to the agent, tool call arguments, and text the agent produced. Tool *results*
    never do.
    """

    __tablename__ = "run_event_blobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("run_events.id"), index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
