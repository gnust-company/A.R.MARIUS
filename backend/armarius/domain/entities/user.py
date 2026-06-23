"""User entity — human users of Armarius (Patrons)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from armarius.shared.clock import utcnow


class UserRole(StrEnum):
    """User roles for governance and access control."""

    PATRON = "patron"  # Full access to owned workspaces
    MEMBER = "member"  # Limited access, invited to workspaces
    ADMIN = "admin"  # System administrator


@dataclass
class User:
    """A human user of Armarius — the Patron who commissions tasks."""

    id: UUID
    email: str
    username: str
    full_name: str
    hashed_password: str
    role: UserRole = UserRole.PATRON
    is_active: bool = True
    is_verified: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        email: str,
        username: str,
        full_name: str,
        password: str,
        role: UserRole = UserRole.PATRON,
    ) -> User:
        """Create a new user (password will be hashed by the service layer)."""
        return cls(
            id=uuid4(),
            email=email.lower(),
            username=username,
            full_name=full_name,
            hashed_password=password,  # Will be hashed by the service
            role=role,
            is_active=True,
            is_verified=False,
            created_at=utcnow(),
        )

    def update_last_login(self) -> None:
        """Update the last login timestamp."""
        self.last_login_at = utcnow()
