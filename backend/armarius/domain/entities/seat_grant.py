"""SeatGrant — who sits in which seat, right now (LLD §2.4, §3.3).

A row is a **live seat and nothing else**. There is no application step and no accept step:
the seat is taken the moment the Patron puts a Marius in it, and the only way out is for
the row to go.

It used to keep its own history. Revoking flipped a `status` column to `revoked` and
re-granting wrote a *second* row beside the first, so "who holds this seat" was a question
about the newest row that said `granted` — and every one of the eight readers had to
remember that. One of them did not, read the stale row, and concluded the project's own
Leader held no role at all. Nothing in the running system ever read a revoked row for any
other purpose, so the history existed purely as a trap. A revoke now deletes the row: the
table says who is seated, and there is nothing else in it to misread.

The seat points at the role **by identity**. A `role_key` is a label the patron can edit;
pointing at it meant a renamed role silently emptied its own seats, and it left the two
tables joinable only by string comparison spread across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class SeatGrant:
    project_id: UUID
    role_id: UUID
    marius_id: UUID
    id: UUID = field(default_factory=uuid4)
    # Which patron put this agent in the seat (FR-034). This is what decides who must
    # sign for the agent's output — recorded at grant time, never inferred afterwards.
    # Today it always resolves to the workspace owner; the day a project has more than one
    # patron, an inferred value would be a guess nobody could tell apart from the truth.
    granted_by_user_id: str | None = None
    granted_at: datetime | None = None
    created_at: datetime | None = None
