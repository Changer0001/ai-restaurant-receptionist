"""
Reservation Request Business Logic

Reservations are created entirely by the conversation engine
(app/conversation/tools.py.create_reservation_request) during a live
call — this module is read/status-update only, for the admin
dashboard's reservation queue: staff review each pending request and
mark it confirmed or declined (there is no availability check anywhere
in this system, so that decision is always a human's — see
docs/roadmap.md's "Reservation availability" entry).
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reservation, ReservationStatusEnum


async def list_reservations_for_restaurant(
    db: AsyncSession,
    restaurant_id: str,
    *,
    status_filter: Optional[ReservationStatusEnum] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Reservation]:
    query = select(Reservation).where(Reservation.restaurant_id == restaurant_id)
    if status_filter is not None:
        query = query.where(Reservation.status == status_filter)
    query = query.order_by(Reservation.reservation_date.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_reservation_or_404(
    db: AsyncSession, restaurant_id: str, reservation_id: str
) -> Reservation:
    result = await db.execute(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.restaurant_id == restaurant_id,
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return reservation


async def update_reservation_status(
    db: AsyncSession, restaurant_id: str, reservation_id: str, new_status: ReservationStatusEnum
) -> Reservation:
    reservation = await get_reservation_or_404(db, restaurant_id, reservation_id)
    reservation.status = new_status
    await db.flush()
    await db.refresh(reservation)
    return reservation
