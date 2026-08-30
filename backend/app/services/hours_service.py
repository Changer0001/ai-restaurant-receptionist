"""Restaurant operating-hours business logic."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RestaurantHours
from app.schemas.hours import HoursEntry


async def get_hours(db: AsyncSession, restaurant_id: str) -> list[RestaurantHours]:
    result = await db.execute(
        select(RestaurantHours)
        .where(RestaurantHours.restaurant_id == restaurant_id)
        .order_by(RestaurantHours.day_of_week)
    )
    return list(result.scalars().all())


async def replace_hours(
    db: AsyncSession, restaurant_id: str, entries: list[HoursEntry]
) -> list[RestaurantHours]:
    """
    Atomically replace the restaurant's entire weekly schedule.

    Delete-then-insert (rather than diffing) keeps this simple and correct
    for a small, bounded set of rows (at most 7) — the schedule is always
    submitted as a complete week from the admin UI, never partially.
    """
    await db.execute(delete(RestaurantHours).where(RestaurantHours.restaurant_id == restaurant_id))
    await db.flush()

    rows = [
        RestaurantHours(
            restaurant_id=restaurant_id,
            day_of_week=entry.day_of_week,
            opening_time=entry.opening_time,
            closing_time=entry.closing_time,
            is_closed=entry.is_closed,
        )
        for entry in entries
    ]
    db.add_all(rows)
    await db.flush()

    return await get_hours(db, restaurant_id)
