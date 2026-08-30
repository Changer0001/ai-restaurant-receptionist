"""Tests for app.services.restaurant_service's phone-number lookups."""

from app.db.models import Restaurant, RestaurantPhoneNumber
from app.services import restaurant_service


async def test_get_active_phone_number_for_restaurant_returns_the_active_number(
    db_session, restaurant
):
    db_session.add(
        RestaurantPhoneNumber(
            restaurant_id=restaurant.id, phone_number="+15551110000", is_active=True
        )
    )
    await db_session.commit()

    number = await restaurant_service.get_active_phone_number_for_restaurant(
        db_session, restaurant.id
    )

    assert number == "+15551110000"


async def test_get_active_phone_number_for_restaurant_ignores_inactive_numbers(
    db_session, restaurant
):
    db_session.add(
        RestaurantPhoneNumber(
            restaurant_id=restaurant.id, phone_number="+15551110000", is_active=False
        )
    )
    await db_session.commit()

    number = await restaurant_service.get_active_phone_number_for_restaurant(
        db_session, restaurant.id
    )

    assert number is None


async def test_get_active_phone_number_for_restaurant_returns_none_when_unconfigured(
    db_session, restaurant
):
    number = await restaurant_service.get_active_phone_number_for_restaurant(
        db_session, restaurant.id
    )

    assert number is None


async def test_get_active_phone_number_for_restaurant_never_leaks_another_restaurants_number(
    db_session, restaurant
):
    other = Restaurant(name="Other Place", timezone="America/New_York", is_active=True)
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        RestaurantPhoneNumber(restaurant_id=other.id, phone_number="+15552220000", is_active=True)
    )
    await db_session.commit()

    number = await restaurant_service.get_active_phone_number_for_restaurant(
        db_session, restaurant.id
    )

    assert number is None
