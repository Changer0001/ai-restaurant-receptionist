"""Restaurant FAQ business logic."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RestaurantFAQ
from app.schemas.faq import FAQCreate, FAQUpdate


async def list_faqs(db: AsyncSession, restaurant_id: str, *, active_only: bool = False) -> list[RestaurantFAQ]:
    query = select(RestaurantFAQ).where(RestaurantFAQ.restaurant_id == restaurant_id)
    if active_only:
        query = query.where(RestaurantFAQ.is_active.is_(True))
    query = query.order_by(RestaurantFAQ.category, RestaurantFAQ.question)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_faq(db: AsyncSession, restaurant_id: str, data: FAQCreate) -> RestaurantFAQ:
    faq = RestaurantFAQ(restaurant_id=restaurant_id, **data.model_dump())
    db.add(faq)
    await db.flush()
    await db.refresh(faq)
    return faq


async def _get_faq_or_404(db: AsyncSession, restaurant_id: str, faq_id: str) -> RestaurantFAQ:
    result = await db.execute(
        select(RestaurantFAQ).where(
            RestaurantFAQ.id == faq_id,
            RestaurantFAQ.restaurant_id == restaurant_id,
        )
    )
    faq = result.scalar_one_or_none()
    if faq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ not found")
    return faq


async def update_faq(db: AsyncSession, restaurant_id: str, faq_id: str, data: FAQUpdate) -> RestaurantFAQ:
    faq = await _get_faq_or_404(db, restaurant_id, faq_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(faq, field, value)
    await db.flush()
    await db.refresh(faq)
    return faq


async def delete_faq(db: AsyncSession, restaurant_id: str, faq_id: str) -> None:
    faq = await _get_faq_or_404(db, restaurant_id, faq_id)
    await db.delete(faq)
    await db.flush()
