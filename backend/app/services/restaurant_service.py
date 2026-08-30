"""Restaurant business logic."""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Restaurant, RestaurantPhoneNumber
from app.schemas.restaurant import RestaurantUpdate


async def get_restaurant_or_404(db: AsyncSession, restaurant_id: str) -> Restaurant:
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def update_restaurant(
    db: AsyncSession, restaurant_id: str, data: RestaurantUpdate
) -> Restaurant:
    restaurant = await get_restaurant_or_404(db, restaurant_id)

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(restaurant, field, value)

    await db.flush()
    await db.refresh(restaurant)
    return restaurant


async def list_restaurants_for_platform_admin(db: AsyncSession) -> list[Restaurant]:
    result = await db.execute(select(Restaurant).order_by(Restaurant.name))
    return list(result.scalars().all())


async def get_restaurant_by_phone_number(
    db: AsyncSession, phone_number: str
) -> Optional[Restaurant]:
    """
    Resolve an incoming Twilio call's "To" number to the restaurant it
    belongs to — the first step of every inbound call
    (RestaurantPhoneNumber -> restaurant_id -> Restaurant), and the
    entire basis of this system's multi-tenancy for voice: there is no
    other way a call gets scoped to one restaurant's data.

    Returns None for an unmapped or inactive number/restaurant — the
    caller (the voice webhook) must treat that as "cannot route this
    call," never fall back to any restaurant.
    """
    result = await db.execute(
        select(Restaurant)
        .join(RestaurantPhoneNumber, RestaurantPhoneNumber.restaurant_id == Restaurant.id)
        .where(
            RestaurantPhoneNumber.phone_number == phone_number,
            RestaurantPhoneNumber.is_active.is_(True),
            Restaurant.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()
