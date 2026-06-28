"""SeatGrant — a system-only seat assignment (LLD §2.4, §3.3).

Agents never apply and there is no accept step: a grant is `granted` the moment the
Patron assigns a Marius to a role seat, and the only transition out is `revoked`.
Project activation keys off liveness (every seated agent ONLINE), NOT grant state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class SeatGrantStatus(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class SeatGrantError(Exception):
    """Raised on an illegal grant transition (e.g. revoking an already-revoked grant)."""


@dataclass
class SeatGrant:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    role_key: str = ""
    marius_id: UUID | None = None
    status: SeatGrantStatus = SeatGrantStatus.GRANTED
    granted_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == SeatGrantStatus.GRANTED

    def revoke(self) -> None:
        """The only exit from `granted` (LLD §3.3). Idempotent revoke is an error."""
        if self.status != SeatGrantStatus.GRANTED:
            raise SeatGrantError(f"Cannot revoke a seat that is '{self.status}'.")
        self.status = SeatGrantStatus.REVOKED
