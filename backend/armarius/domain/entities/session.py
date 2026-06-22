"""AgentTaskSession — durable link between a (Marius, adapter, task) and a runtime session.

Mirrors Paperclip's `agent_task_sessions` (§4): the native session handle returned
by the adapter is stored in `session_params_json` so the next wake of the *same*
Marius on the *same* task can resume instead of cold-starting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class AgentTaskSession:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    marius_id: UUID | None = None
    adapter_type: str = ""
    task_id: UUID | None = None
    # Native handle (e.g. Hermes {session_id, session_key}) — opaque to the domain.
    session_params_json: dict = field(default_factory=dict)
    session_display_id: str | None = None
    last_run_id: UUID | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
