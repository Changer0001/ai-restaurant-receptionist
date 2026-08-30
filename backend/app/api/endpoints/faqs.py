"""Restaurant FAQ endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_restaurant_access, require_restaurant_roles
from app.db.models import User, UserRoleEnum
from app.db.session import get_db_session
from app.schemas.faq import FAQCreate, FAQRead, FAQUpdate
from app.services import faq_service

router = APIRouter()

_EDITOR_ROLES = (UserRoleEnum.RESTAURANT_OWNER, UserRoleEnum.RESTAURANT_MANAGER)


@router.get("/{restaurant_id}/faqs", response_model=list[FAQRead])
async def list_faqs(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_access),
):
    return await faq_service.list_faqs(db, restaurant_id)


@router.post("/{restaurant_id}/faqs", response_model=FAQRead, status_code=201)
async def create_faq(
    restaurant_id: str,
    data: FAQCreate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    return await faq_service.create_faq(db, restaurant_id, data)


@router.patch("/{restaurant_id}/faqs/{faq_id}", response_model=FAQRead)
async def update_faq(
    restaurant_id: str,
    faq_id: str,
    data: FAQUpdate,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    return await faq_service.update_faq(db, restaurant_id, faq_id, data)


@router.delete("/{restaurant_id}/faqs/{faq_id}", status_code=204)
async def delete_faq(
    restaurant_id: str,
    faq_id: str,
    db: AsyncSession = Depends(get_db_session),
    _: User = Depends(require_restaurant_roles(*_EDITOR_ROLES)),
):
    await faq_service.delete_faq(db, restaurant_id, faq_id)
