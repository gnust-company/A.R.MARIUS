"""Placement — the one place an agent works, fixed when the agent is created (FR-007).

An agent does not float. It is put somewhere at birth, it stays there for life, and if that
somewhere stops working the agent is offline rather than quietly moved. Moving an agent is a
decision a person makes by replacing it, never something the system does behind their back.

What this layer is allowed to know about that place is deliberately thin: it exists, it
belongs to a workspace, and it is open for work or closed with a reason. It knows nothing
about *what* the place is or *where* it physically sits — that is infrastructure's, and the
whole point of keeping it there is that a second kind of place can arrive without a single
line of business logic being reopened (Constitution III, FR-035, FR-037).

The reason travels as a code, never a sentence: two audiences read it in two languages, and
only the edge that knows which reader it is talking to can turn it into words (Constitution
VII, FR-084a).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

# An agent that was never put anywhere. Stated here rather than wherever the absence is
# noticed, because it is the one not-ready reason this layer can name on its own: no
# knowledge of what a place is goes into knowing an agent has none (FR-007f).
NOT_PLACED = "not_placed"

# The place is shut and said nothing about why. Rare, and kept as a code anyway — a screen
# that shows an agent offline with a blank space beside it is the failure FR-006c names.
PLACEMENT_NOT_READY = "placement_not_ready"


@dataclass(frozen=True)
class Placement:
    id: UUID
    workspace_id: UUID
    # Open for work. A closed placement still exists and still holds every agent that was
    # put there — those agents are offline, which is a state with a defined meaning rather
    # than a silent failure (FR-007f).
    ready: bool = False
    not_ready_reason: str | None = None
