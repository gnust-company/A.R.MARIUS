"""Authentication use cases — register, login, token refresh."""

from __future__ import annotations

import re
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.user import User, UserRole
from armarius.infrastructure.security.jwt import JWTService
from armarius.infrastructure.security.password import PasswordService
from armarius.shared.errors import CodedError


class AuthError(CodedError):
    """Base exception for auth errors."""


class DuplicateEmailError(AuthError):
    """That email already has an account."""


class DuplicateUsernameError(AuthError):
    """The handle derived from the email is taken."""


class InvalidCredentialsError(AuthError):
    """Wrong email or password — and the same answer for an unknown account, so a
    caller cannot tell the two apart and enumerate who is registered."""


def _username_from_email(email: str) -> str:
    """Derive a safe handle from the email local-part (login is by email anyway)."""
    local = email.split("@", 1)[0]
    handle = re.sub(r"[^a-zA-Z0-9_-]+", "", local).strip("-_")
    return handle or "user"


class AuthService:
    """Authentication and user registration service."""

    def __init__(
        self,
        uow_factory: UowFactory,
        workspaces: WorkspaceService,
        jwt_service: JWTService | None = None,
        password_service: PasswordService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._workspaces = workspaces
        self._jwt = jwt_service or JWTService()
        self._pwd = password_service or PasswordService()

    async def register(
        self,
        email: str,
        full_name: str,
        password: str,
        username: str | None = None,
        role: UserRole | None = None,
    ) -> tuple[User, str, str]:
        """Register a new user. Returns (user, access_token, refresh_token).

        Login is by email; `username` is just an internal handle. When omitted it is
        derived from the email local-part and made unique automatically.

        Raises:
            DuplicateEmailError: if email is already registered
        """
        async with self._uow() as uow:
            # Check for existing email
            existing_email = await uow.users.get_by_email(email)
            if existing_email is not None:
                raise DuplicateEmailError("email_already_registered")

            # Derive a unique internal username from the email if not provided.
            if username:
                base = username
            else:
                base = _username_from_email(email)
            candidate = base
            suffix = 1
            while await uow.users.get_by_username(candidate) is not None:
                suffix += 1
                candidate = f"{base}{suffix}"
            username = candidate

            # Hash the password
            hashed_password = self._pwd.hash(password)

            # Create the user
            user = User.create(
                email=email,
                username=username,
                full_name=full_name,
                password=hashed_password,
                role=role or UserRole.PATRON,
            )

            user = await uow.users.add(user)
            await uow.commit()

        # Provision a personal workspace so the new user lands somewhere real
        # (not someone else's demo data). Idempotent.
        await self._workspaces.ensure_personal_workspace(user)

        # Generate tokens
        access_token = self._jwt.create_access_token(user.id)
        refresh_token = self._jwt.create_refresh_token(user.id)

        return user, access_token, refresh_token

    async def login(
        self, email: str, password: str
    ) -> tuple[User, str, str]:
        """Login a user. Returns (user, access_token, refresh_token).

        Raises:
            InvalidCredentialsError: if email or password is invalid
        """
        async with self._uow() as uow:
            user = await uow.users.get_by_email(email)
            if user is None:
                # Timing attack protection: hash the password anyway
                self._pwd.hash(password)
                raise InvalidCredentialsError("invalid_credentials")

            if not self._pwd.verify(password, user.hashed_password):
                raise InvalidCredentialsError("invalid_credentials")

            if not user.is_active:
                raise InvalidCredentialsError("invalid_credentials")

            # Update last login
            user.update_last_login()
            await uow.users.update(user)
            await uow.commit()

        # Generate tokens
        access_token = self._jwt.create_access_token(user.id)
        refresh_token = self._jwt.create_refresh_token(user.id)

        return user, access_token, refresh_token

    async def refresh_tokens(self, refresh_token: str) -> tuple[str, str]:
        """Refresh access token using refresh token. Returns (access_token, refresh_token).

        Raises:
            InvalidCredentialsError: if refresh token is invalid
        """
        user_id = self._jwt.verify_refresh_token(refresh_token)

        async with self._uow() as uow:
            user = await uow.users.get(user_id)
            if user is None or not user.is_active:
                raise InvalidCredentialsError("invalid_credentials")

        # Generate new tokens
        new_access = self._jwt.create_access_token(user_id)
        new_refresh = self._jwt.create_refresh_token(user_id)

        return new_access, new_refresh

    async def get_current_user(self, user_id: UUID) -> User | None:
        """Get a user by ID (for authenticated requests)."""
        async with self._uow() as uow:
            return await uow.users.get(user_id)
