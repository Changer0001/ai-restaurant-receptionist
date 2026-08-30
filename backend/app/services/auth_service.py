"""Authentication business logic: registration, login, token refresh."""


from fastapi import HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import Restaurant, User, UserRoleEnum
from app.schemas.auth import RegisterRequest, TokenResponse


async def register_restaurant_owner(db: AsyncSession, data: RegisterRequest) -> TokenResponse:
    """
    Create a new Restaurant plus its first User (restaurant_owner) and
    return tokens for immediate login. Both rows are created in the same
    session/transaction — if the commit fails, neither is left behind.
    """
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    restaurant = Restaurant(
        name=data.restaurant_name,
        timezone=data.restaurant_timezone,
        is_active=True,
    )
    db.add(restaurant)
    await db.flush()  # populates restaurant.id without ending the transaction

    user = User(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        hashed_password=hash_password(data.password),
        role=UserRoleEnum.RESTAURANT_OWNER,
        restaurant_id=restaurant.id,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    return issue_tokens(user)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """Verify credentials and return the User row, or raise 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
    )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.hashed_password):
        raise unauthorized

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    return user


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    Role and restaurant_id are re-read from the database rather than
    carried over from the old token, so a role change since the refresh
    token was issued takes effect immediately.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )

    try:
        payload = decode_token(refresh_token, TokenType.REFRESH)
    except JWTError as exc:
        raise unauthorized from exc

    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise unauthorized

    return issue_tokens(user)


def issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.restaurant_id),
        refresh_token=create_refresh_token(user.id),
    )
