"""Authentication API endpoints — register, login, refresh, me."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, EmailStr, Field

from armarius.application.use_cases.auth import (
    DuplicateEmailError,
    InvalidCredentialsError,
)
from armarius.domain.entities.user import User
from armarius.presentation.deps import ContainerDep
from armarius.shared.errors import Conflict, Forbidden, Unauthorized

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserRegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=100)
    # Optional internal handle; derived from the email when omitted. Login is by email.
    username: str | None = Field(
        default=None, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$"
    )


class UserLoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenRefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    created_at: str | None = None
    last_login_at: str | None = None
    # Where this person is in the three first steps, and whether they are through them
    # (FR-100, FR-104). Sent on `/auth/me` because that is the one call the app makes before
    # it decides which screen to show, and the answer *send them to the first steps* has to
    # come from the same place as *who they are*.
    onboarding_step: int = 0
    onboarded: bool = True

    @classmethod
    def from_entity(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=str(user.role),
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at.isoformat() if user.created_at else None,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
            onboarding_step=user.onboarding_step,
            onboarded=user.onboarded,
        )


class AuthTokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterOut(BaseModel):
    user: UserOut
    tokens: AuthTokensOut


class LoginOut(BaseModel):
    user: UserOut
    tokens: AuthTokensOut


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    container: ContainerDep = None,  # type: ignore[assignment]
) -> User:
    """Resolve the authenticated user from a Bearer token (human user API)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing_bearer_token")

    token = authorization.split(" ", 1)[1].strip()

    try:
        user_id = container.jwt_service.verify_access_token(token)
    except ValueError as e:
        raise Unauthorized("invalid_access_token") from e

    user = await container.auth.get_current_user(user_id)
    if user is None:
        raise Unauthorized("user_not_found")

    if not user.is_active:
        raise Forbidden("user_inactive")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED
)
async def register(
    data: UserRegisterIn,
    container: ContainerDep,
) -> RegisterOut:
    """Register a new user account."""
    try:
        user, access, refresh = await container.auth.register(
            email=data.email,
            username=data.username,
            full_name=data.full_name,
            password=data.password,
        )
    except DuplicateEmailError:
        raise Conflict("email_already_registered") from None

    return RegisterOut(
        user=UserOut.from_entity(user),
        tokens=AuthTokensOut(access_token=access, refresh_token=refresh),
    )


@router.post("/login", response_model=LoginOut)
async def login(
    data: UserLoginIn,
    container: ContainerDep,
) -> LoginOut:
    """Login with email and password."""
    try:
        user, access, refresh = await container.auth.login(
            email=data.email, password=data.password
        )
    except InvalidCredentialsError:
        raise Unauthorized("invalid_credentials") from None

    return LoginOut(
        user=UserOut.from_entity(user),
        tokens=AuthTokensOut(access_token=access, refresh_token=refresh),
    )


@router.post("/refresh", response_model=AuthTokensOut)
async def refresh(
    data: TokenRefreshIn,
    container: ContainerDep,
) -> AuthTokensOut:
    """Refresh access token using refresh token."""
    try:
        access, refresh = await container.auth.refresh_tokens(data.refresh_token)
    except InvalidCredentialsError:
        raise Unauthorized("invalid_refresh_token") from None

    return AuthTokensOut(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> UserOut:
    """Get current authenticated user."""
    return UserOut.from_entity(current_user)


class UpdateMeIn(BaseModel):
    """What a person may change about themselves (FR-101, FR-104).

    Three things, and the list is short on purpose. Email and password are identity and are
    changed through their own doors with their own checks; the role is not the holder's to set
    at all. What is here is the display name — which until now had no door, so whatever somebody
    typed while signing up was permanent — and where they are in the three first steps.

    Every field is optional and only what is sent is touched. A screen that saves one field
    must not have to send back the rest, because a client that rebuilds the whole object is a
    client that can quietly undo a change made in another tab.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    onboarding_step: int | None = Field(default=None, ge=0, le=3)
    # Not a step number: finishing is its own fact (see `User.onboarded`). Sending `false` does
    # not un-finish anything — there is no product reason to put somebody back through the
    # first steps, and a door that could would be a door that does it by accident.
    onboarding_done: bool | None = None


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateMeIn, current_user: CurrentUser, container: ContainerDep
) -> UserOut:
    """Change your own display name, or record how far you got through the first steps."""
    updated = await container.auth.update_self(
        current_user.id,
        full_name=body.full_name,
        onboarding_step=body.onboarding_step,
        onboarding_done=body.onboarding_done,
    )
    return UserOut.from_entity(updated)
