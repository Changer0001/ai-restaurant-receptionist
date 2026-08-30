"""
Shared API Dependencies

Authentication and tenant-authorization dependencies used by every
protected endpoint. This is where multi-tenant isolation is actually
enforced — never trust a restaurant_id from the request path/body alone.
"""


from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenType, decode_token
from app.db.models import User, UserRoleEnum
from app.db.session import get_db_session

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the bearer access token to a live, active User row.

    Re-fetching from the database (rather than trusting the JWT's role/
    restaurant_id claims alone) means a deactivated user or a role change
    takes effect on their very next request instead of only once their
    access token happens to expire.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials, TokenType.ACCESS)
    except JWTError as exc:
        raise unauthorized from exc

    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise unauthorized

    return user


def require_roles(*allowed_roles: UserRoleEnum):
    """Dependency factory: 403s unless the current user has one of the
    given roles. Platform admins are NOT implicitly included — pass
    UserRoleEnum.PLATFORM_ADMIN explicitly where they should have access."""

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _check


async def require_restaurant_access(
    restaurant_id: str = Path(...),
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Enforce tenant isolation: the path's restaurant_id must match the
    caller's own restaurant, unless they're a platform admin.

    This is the one check that MUST run on every restaurant-scoped route —
    it is the actual authorization boundary, not the frontend, and not the
    restaurant_id embedded in the JWT (which we deliberately re-verify
    against the current, live user row rather than trusting the token).
    """
    if current_user.role == UserRoleEnum.PLATFORM_ADMIN:
        return current_user

    if current_user.restaurant_id != restaurant_id:
        # 404 rather than 403: don't confirm to a caller poking at IDs
        # they don't own that a given restaurant_id even exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant not found",
        )

    return current_user


def require_restaurant_roles(*allowed_roles: UserRoleEnum):
    """Combines tenant-scoping with a role check for restaurant-scoped
    write endpoints (e.g. only owner/manager may edit hours, not staff)."""

    async def _check(
        restaurant_id: str = Path(...),
        current_user: User = Depends(get_current_user),
    ) -> User:
        await require_restaurant_access(restaurant_id, current_user)
        if current_user.role not in allowed_roles and current_user.role != UserRoleEnum.PLATFORM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _check
