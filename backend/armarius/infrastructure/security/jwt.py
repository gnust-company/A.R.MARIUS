"""JWT token service for user authentication."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt

from armarius.shared.clock import utcnow
from armarius.shared.config import settings


class TokenPayload:
    """JWT token payload."""

    sub: str  # user_id
    exp: datetime
    type: str  # "access" or "refresh"
    iat: datetime

    def __init__(
        self, sub: str, exp: datetime, type: str, iat: datetime | None = None
    ):
        self.sub = sub
        self.exp = exp
        self.type = type
        self.iat = iat or utcnow()


class JWTService:
    """JWT token creation and validation."""

    def __init__(self) -> None:
        self.secret = settings.jwt_secret
        self.algorithm = settings.jwt_algorithm
        self.access_expire_minutes = settings.jwt_access_expire_minutes
        self.refresh_expire_days = settings.jwt_refresh_expire_days

    def create_access_token(self, user_id: UUID) -> str:
        """Create a short-lived access token."""
        now = utcnow()
        expire = now + timedelta(minutes=self.access_expire_minutes)
        to_encode = {
            "sub": str(user_id),
            "exp": expire,
            "type": "access",
            "iat": now,
        }
        return jwt.encode(to_encode, self.secret, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: UUID) -> str:
        """Create a long-lived refresh token."""
        now = utcnow()
        expire = now + timedelta(days=self.refresh_expire_days)
        to_encode = {
            "sub": str(user_id),
            "exp": expire,
            "type": "refresh",
            "iat": now,
        }
        return jwt.encode(to_encode, self.secret, algorithm=self.algorithm)

    def decode_and_validate_token(self, token: str) -> TokenPayload:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return TokenPayload(
                sub=payload["sub"],
                exp=datetime.fromtimestamp(payload["exp"]),
                type=payload.get("type", "access"),
                iat=datetime.fromtimestamp(payload["iat"]),
            )
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}") from e

    def verify_access_token(self, token: str) -> UUID:
        """Verify an access token and return the user_id."""
        payload = self.decode_and_validate_token(token)
        if payload.type != "access":
            raise ValueError("Expected an access token")
        return UUID(payload.sub)

    def verify_refresh_token(self, token: str) -> UUID:
        """Verify a refresh token and return the user_id."""
        payload = self.decode_and_validate_token(token)
        if payload.type != "refresh":
            raise ValueError("Expected a refresh token")
        return UUID(payload.sub)
