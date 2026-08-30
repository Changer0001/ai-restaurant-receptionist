"""Restaurant management endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_restaurant_access, require_restaurant_roles
from app.db.models import User, UserRoleEnum
from app.db.session import get_db_session
from app.schemas.restaurant import RestaurantRead, RestaurantUpdate
from app.services import restaurant_service

router = APIRouter()


@router.get("", response_model=list[RestaurantRead])
async def list_restaurants(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """
    Platform admins see every restaurant; everyone else sees only the
    single restaurant they belong to (the User model is single-tenant
    per user — no cross-restaurant staff in the MVP).
    """
    if current_user.role == UserRoleEnum.PLATFORM_ADMIN:
        return await restaurant_service.list_restaurants_for_platform_admin(db)

    if current_user.restaurant_id is None:
        return []

    restaurant = await restaurant_service.get_restaurant_or_404(db, current_user.restaurant_id)
    return [restaurant]


@router.get("/{restaurant_id}", response_model=RestaurantRead)
async def get_restaurant(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await restaurant_service.get_restaurant_or_404(db, restaurant_id)


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
async def patch_restaurant(
    restaurant_id: str,
    data: RestaurantUpdate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(
        require_restaurant_roles(UserRoleEnum.RESTAURANT_OWNER, UserRoleEnum.RESTAURANT_MANAGER)
    ),
):
    return await restaurant_service.update_restaurant(db, restaurant_id, data)
