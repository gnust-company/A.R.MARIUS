"""spec002: delete every row the external-gateway path produced

FR-040a: the old gateway path is treated as if it had never existed — no migration rule,
no backward compatibility, no "legacy agent" state. Removing the code alone would leave
rows behind that point at an adapter no longer in the registry: an agent whose every wake
would now raise `unknown_adapter`, and runs, sessions and pending wakes hanging off it.
That is the same dead weight FR-040a bans, only in data rather than in code.

Two different things happen here, and the difference is deliberate:

* **Deleted** — rows that exist *only* to serve one agent and mean nothing without it:
  its runs (and their events and blobs and claims), its task sessions, its pending wakes,
  its seat grants, its workplace binding.
* **Nulled** — pointers *from* rows that outlive the agent. A comment still says what it
  said and a task still has to be done; only the name of who did it is gone. Deleting
  those rows would throw away work the agent merely touched.

`downgrade()` is a no-op. A purge has no inverse: the rows are gone and no earlier
revision can conjure them back. Rolling past this point gives you the old schema, not the
old data — which is exactly what FR-040a asks for.

Safe because the system has no outside users yet (spec Assumptions).

Revision ID: d8a3b6c41e57
Revises: c7f2a5e18d94
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8a3b6c41e57'
down_revision: Union[str, Sequence[str], None] = 'c7f2a5e18d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every agent that ran behind the external gateway.
_DOOMED = "SELECT id FROM mariuses WHERE adapter_type = 'hermes_gateway'"
# Their runs. Named separately because three tables hang off runs, not off agents.
_DOOMED_RUNS = f"SELECT id FROM runs WHERE marius_id IN ({_DOOMED})"


def upgrade() -> None:
    # Children first, parents last — the FKs to `runs` and `mariuses` are real and will
    # refuse a delete that leaves them dangling.
    op.execute(
        "DELETE FROM run_event_blobs WHERE run_event_id IN "
        f"(SELECT id FROM run_events WHERE run_id IN ({_DOOMED_RUNS}))"
    )
    op.execute(f"DELETE FROM run_events WHERE run_id IN ({_DOOMED_RUNS})")
    op.execute(f"DELETE FROM run_claims WHERE run_id IN ({_DOOMED_RUNS})")
    op.execute(f"DELETE FROM runs WHERE marius_id IN ({_DOOMED})")

    op.execute(f"DELETE FROM agent_task_sessions WHERE marius_id IN ({_DOOMED})")
    op.execute(f"DELETE FROM wakeup_requests WHERE marius_id IN ({_DOOMED})")
    op.execute(f"DELETE FROM seat_grants WHERE marius_id IN ({_DOOMED})")
    op.execute(f"DELETE FROM agent_workplace_bindings WHERE marius_id IN ({_DOOMED})")

    # Work that survives its author. Losing the pointer is the point: it must not name a
    # row that is about to stop existing.
    for table, column in (
        ("workspaces", "workspace_agent_id"),
        ("tasks", "assigned_marius_id"),
        ("tasks", "created_by_marius_id"),
        ("task_approvals", "signer_marius_id"),
        ("comments", "author_marius_id"),
        ("project_leader_conversations", "leader_marius_id"),
        ("artifacts", "marius_id"),
        ("task_logs", "actor_marius_id"),
    ):
        op.execute(
            f"UPDATE {table} SET {column} = NULL WHERE {column} IN ({_DOOMED})"
        )

    op.execute("DELETE FROM mariuses WHERE adapter_type = 'hermes_gateway'")


def downgrade() -> None:
    """Nothing to undo — deleted rows do not come back."""
