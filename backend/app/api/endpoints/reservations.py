"""
Reservation request endpoints.

Reservations are created entirely by the conversation engine during a
live call — there is no POST endpoint here for staff to create one by
hand (out of scope for the MVP, see docs/roadmap.md). Staff can list,
view, and update the status of a reservation request (confirm/decline
it — the human judgment call this system always defers to, since there
is no table-inventory/availability check anywhere in this system).
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_restaurant_access, require_restaurant_roles
from app.db.models import ReservationStatusEnum, User, UserRoleEnum
from app.db.session import get_db_session
from app.schemas.reservation import ReservationRead, ReservationStatusUpdate
from app.services import reservation_service

router = APIRouter()

# Unlike editing the restaurant's profile/hours/FAQs (owner/manager
# only), updating a reservation's status is front-of-house's day-to-day
# job — staff can do it too.
_STATUS_UPDATE_ROLES = (
    UserRoleEnum.RESTAURANT_OWNER,
    UserRoleEnum.RESTAURANT_MANAGER,
    UserRoleEnum.RESTAURANT_STAFF,
)


@router.get("/{restaurant_id}/reservations", response_model=list[ReservationRead])
async def list_reservations(
    restaurant_id: str,
    status_filter: Optional[ReservationStatusEnum] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await reservation_service.list_reservations_for_restaurant(
        db, restaurant_id, status_filter=status_filter, limit=limit, offset=offset
    )


@router.get("/{restaurant_id}/reservations/{reservation_id}", response_model=ReservationRead)
async def get_reservation(
    restaurant_id: str,
    reservation_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await reservation_service.get_reservation_or_404(db, restaurant_id, reservation_id)


@router.patch("/{restaurant_id}/reservations/{reservation_id}", response_model=ReservationRead)
async def update_reservation(
    restaurant_id: str,
    reservation_id: str,
    data: ReservationStatusUpdate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_roles(*_STATUS_UPDATE_ROLES)),
):
    return await reservation_service.update_reservation_status(
        db, restaurant_id, reservation_id, data.status
    )
