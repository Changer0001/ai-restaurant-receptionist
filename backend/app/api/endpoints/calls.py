"""
Call history endpoints — read-only. Calls are created and updated
entirely by the voice pipeline (app/voice/session.py via the Twilio
webhooks router), never through this API.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_restaurant_access
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.call import CallDetailRead, CallRead
from app.services import call_service

router = APIRouter()


@router.get("/{restaurant_id}/calls", response_model=list[CallRead])
async def list_calls(
    restaurant_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    """Most recent calls first. Any authenticated user belonging to this
    restaurant can view its call history — read access isn't restricted
    to owner/manager the way editing hours/FAQs/profile is."""
    return await call_service.list_calls_for_restaurant(
        db, restaurant_id, limit=limit, offset=offset
    )


@router.get("/{restaurant_id}/calls/{call_id}", response_model=CallDetailRead)
async def get_call(
    restaurant_id: str,
    call_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await call_service.get_call_or_404(db, restaurant_id, call_id)
