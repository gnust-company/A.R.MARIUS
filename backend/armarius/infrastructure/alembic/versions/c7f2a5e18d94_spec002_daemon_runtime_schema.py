"""spec002: the daemon runtime's six tables, plus what the existing tables were missing

Feature 002 moves execution off an external gateway and onto a daemon running on the
user's own machine. That introduces one whole vocabulary — machines, workplaces, claims —
and every word of it stays in infrastructure. The domain layer gets exactly one new
column, `runs.accepted_at`, and it deliberately does not name a machine.

Three groups of change:

1. **Six new tables.** `machines` and `workplaces` are what the daemon registers;
   `daemon_link_codes` carries the single-use device-flow code that binds a machine to a
   workspace; `run_claims` is who currently holds a run and until when;
   `agent_workplace_bindings` says which workplace an agent runs on;
   `run_event_blobs` holds the full text of an event too large to keep inline.

2. **Columns the existing tables were missing.** `runs.accepted_at` starts the first
   drive. Four columns on `run_events` record *why* a payload is incomplete, so a gap on
   screen can be explained rather than just shown. Two on `artifacts` build the dedup key.

3. **Two indexes.** `(run_id, type)` because filtering the log by event kind is required.
   `(workplace_id) WHERE machine_id IS NULL` because the claim statement runs on every
   poll from every machine, and it must stay cheap; the partial predicate keeps the index
   to just the runs actually up for grabs.

Downgrade drops all of it. Safe here: nothing outside this feature reads these tables.

Revision ID: c7f2a5e18d94
Revises: b6d1e4a90c72
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f2a5e18d94'
down_revision: Union[str, Sequence[str], None] = 'b6d1e4a90c72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daemon_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("platform", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("symlink_capable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_machines_workspace_id", "machines", ["workspace_id"])
    op.create_index("ix_machines_owner_user_id", "machines", ["owner_user_id"])
    op.create_index("ix_machines_token_hash", "machines", ["token_hash"])

    op.create_table(
        "workplaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("cli_kind", sa.String(length=40), nullable=False),
        sa.Column("cli_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("protocol_family", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("not_ready_reason", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("machine_id", "cli_kind", name="uq_workplace_machine_cli"),
    )
    op.create_index("ix_workplaces_workspace_id", "workplaces", ["workspace_id"])
    op.create_index("ix_workplaces_machine_id", "workplaces", ["machine_id"])

    op.create_table(
        "daemon_link_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("machine_id", sa.Uuid(), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("reported_platform", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("reported_daemon_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("reported_hostname", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_daemon_link_code"),
    )
    op.create_index("ix_daemon_link_codes_code", "daemon_link_codes", ["code"])
    op.create_index("ix_daemon_link_codes_workspace_id", "daemon_link_codes", ["workspace_id"])

    op.create_table(
        "run_claims",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), sa.ForeignKey("workplaces.id"), nullable=False),
        sa.Column("machine_id", sa.Uuid(), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_token_hash", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_run_claims_workspace_id", "run_claims", ["workspace_id"])
    op.create_index("ix_run_claims_run_token_hash", "run_claims", ["run_token_hash"])
    # The hot path: "give me runs on these workplaces that nobody holds". Partial, so the
    # index carries only the free rows instead of every run the workspace ever had.
    op.create_index(
        "ix_run_claims_unclaimed",
        "run_claims",
        ["workplace_id"],
        sqlite_where=sa.text("machine_id IS NULL"),
        postgresql_where=sa.text("machine_id IS NULL"),
    )

    op.create_table(
        "agent_workplace_bindings",
        sa.Column("marius_id", sa.Uuid(), sa.ForeignKey("mariuses.id"), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("workplace_id", sa.Uuid(), sa.ForeignKey("workplaces.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_workplace_bindings_workspace_id", "agent_workplace_bindings", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_workplace_bindings_workplace_id", "agent_workplace_bindings", ["workplace_id"]
    )

    op.create_table(
        "run_event_blobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_event_id", sa.Uuid(), sa.ForeignKey("run_events.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_run_event_blobs_run_event_id", "run_event_blobs", ["run_event_id"])
    op.create_index("ix_run_event_blobs_workspace_id", "run_event_blobs", ["workspace_id"])

    op.add_column("runs", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "run_events",
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("run_events", sa.Column("original_byte_size", sa.Integer(), nullable=True))
    op.add_column("run_events", sa.Column("omission_reason", sa.String(length=40), nullable=True))
    op.add_column(
        "run_events",
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_run_events_run_id_type", "run_events", ["run_id", "type"])

    op.add_column(
        "artifacts",
        sa.Column("logical_name", sa.String(length=300), nullable=False, server_default=""),
    )
    op.add_column(
        "artifacts",
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    # SQLite cannot ALTER TABLE ADD CONSTRAINT; batch mode rebuilds the table instead.
    with op.batch_alter_table("artifacts") as batch:
        batch.create_unique_constraint(
            "uq_artifact_task_name_hash", ["task_id", "logical_name", "content_hash"]
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint("uq_artifact_task_name_hash", type_="unique")
    op.drop_column("artifacts", "content_hash")
    op.drop_column("artifacts", "logical_name")

    op.drop_index("ix_run_events_run_id_type", table_name="run_events")
    op.drop_column("run_events", "redacted")
    op.drop_column("run_events", "omission_reason")
    op.drop_column("run_events", "original_byte_size")
    op.drop_column("run_events", "truncated")

    op.drop_column("runs", "accepted_at")

    op.drop_table("run_event_blobs")
    op.drop_table("agent_workplace_bindings")
    op.drop_table("run_claims")
    op.drop_table("daemon_link_codes")
    op.drop_table("workplaces")
    op.drop_table("machines")
