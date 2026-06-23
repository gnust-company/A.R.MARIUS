"""Password hashing service using bcrypt directly.

We use bcrypt directly rather than via passlib to avoid the passlib/bcrypt version
incompatibility (passlib 1.7.4 breaks on bcrypt >= 4.1). The API is intentionally
tiny: hash + verify.
"""

from __future__ import annotations

import bcrypt


class PasswordService:
    """Password hashing and verification."""

    def hash(self, password: str) -> str:
        """Hash a password for storage. Returns a utf-8 bcrypt hash string."""
        # bcrypt has a 72-byte limit; that's fine for human passwords, but enforce it
        # explicitly so we get a clear error rather than silent truncation surprises.
        pw_bytes = password.encode("utf-8")
        if len(pw_bytes) > 72:
            raise ValueError(
                "password cannot be longer than 72 bytes; truncate manually if necessary"
            )
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a stored hash."""
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except (ValueError, TypeError):
            return False
