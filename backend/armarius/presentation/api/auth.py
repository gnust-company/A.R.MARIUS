"""Authentication API endpoints — register, login, refresh, me."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from armarius.application.use_cases.auth import (
    DuplicateEmailError,
    DuplicateUsernameError,
    InvalidCredentialsError,
)
from armarius.domain.entities.user import User
from armarius.presentation.deps import ContainerDep

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserRegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=100)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )

    token = authorization.split(" ", 1)[1].strip()

    try:
        user_id = container.jwt_service.verify_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        ) from e

    user = await container.auth.get_current_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    except DuplicateUsernameError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        ) from None

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from None

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None

    return AuthTokensOut(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> UserOut:
    """Get current authenticated user."""
    return UserOut.from_entity(current_user)
