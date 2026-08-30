"""Restaurant operating-hours endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_restaurant_access, require_restaurant_roles
from app.db.models import User, UserRoleEnum
from app.db.session import get_db_session
from app.schemas.hours import HoursRead, HoursSetRequest
from app.services import hours_service

router = APIRouter()


@router.get("/{restaurant_id}/hours", response_model=list[HoursRead])
async def get_hours(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await hours_service.get_hours(db, restaurant_id)


@router.put("/{restaurant_id}/hours", response_model=list[HoursRead])
async def put_hours(
    restaurant_id: str,
    data: HoursSetRequest,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(
        require_restaurant_roles(UserRoleEnum.RESTAURANT_OWNER, UserRoleEnum.RESTAURANT_MANAGER)
    ),
):
    return await hours_service.replace_hours(db, restaurant_id, data.hours)
