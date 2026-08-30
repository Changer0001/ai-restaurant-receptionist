"""Integration tests for the reservation-request endpoints (list,
detail, status update) and tenant isolation. Reservations are only
ever created by the conversation engine during a live call, never
through this API — these tests insert Reservation rows directly via
the ORM to set up fixtures."""

from datetime import datetime, timezone

from app.db.models import Reservation, ReservationStatusEnum
from tests.conftest import auth_headers


def _register(client, email, restaurant_name):
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "restaurant_name": restaurant_name,
        "restaurant_timezone": "America/New_York",
    }
    return client.post("/api/auth/register", json=payload).json()


def _make_reservation(restaurant_id: str, **overrides) -> Reservation:
    defaults = {
        "restaurant_id": restaurant_id,
        "customer_name": "Jane Diner",
        "customer_phone": "+15551234567",
        "reservation_date": datetime.now(timezone.utc),
        "reservation_time": "19:00",
        "party_size": 4,
        "status": ReservationStatusEnum.PENDING,
    }
    defaults.update(overrides)
    return Reservation(**defaults)


async def test_list_reservations(client, db_session, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    db_session.add(_make_reservation(rid))
    await db_session.commit()

    resp = client.get(
        f"/api/restaurants/{rid}/reservations", headers=auth_headers(tokens["access_token"])
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["customer_name"] == "Jane Diner"
    assert body[0]["status"] == "pending"


async def test_list_reservations_filters_by_status(client, db_session, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    db_session.add_all(
        [
            _make_reservation(
                rid, customer_name="Pending Person", status=ReservationStatusEnum.PENDING
            ),
            _make_reservation(
                rid, customer_name="Confirmed Person", status=ReservationStatusEnum.CONFIRMED
            ),
        ]
    )
    await db_session.commit()

    resp = client.get(
        f"/api/restaurants/{rid}/reservations?status=confirmed",
        headers=auth_headers(tokens["access_token"]),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["customer_name"] == "Confirmed Person"


async def test_update_reservation_status_confirms_a_pending_request(
    client, db_session, register_payload
):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    reservation = _make_reservation(rid)
    db_session.add(reservation)
    await db_session.commit()

    resp = client.patch(
        f"/api/restaurants/{rid}/reservations/{reservation.id}",
        json={"status": "confirmed"},
        headers=auth_headers(tokens["access_token"]),
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    await db_session.refresh(reservation)
    assert reservation.status == ReservationStatusEnum.CONFIRMED


async def test_get_unknown_reservation_is_404(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.get(
        f"/api/restaurants/{me['restaurant_id']}/reservations/does-not-exist",
        headers=auth_headers(tokens["access_token"]),
    )

    assert resp.status_code == 404


async def test_cannot_view_or_update_another_restaurants_reservation(
    client, db_session, register_payload
):
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    me_a = client.get("/api/auth/me", headers=auth_headers(tokens_a["access_token"])).json()

    reservation_a = _make_reservation(me_a["restaurant_id"])
    db_session.add(reservation_a)
    await db_session.commit()

    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")

    list_resp = client.get(
        f"/api/restaurants/{me_a['restaurant_id']}/reservations",
        headers=auth_headers(tokens_b["access_token"]),
    )
    assert list_resp.status_code == 404

    patch_resp = client.patch(
        f"/api/restaurants/{me_a['restaurant_id']}/reservations/{reservation_a.id}",
        json={"status": "confirmed"},
        headers=auth_headers(tokens_b["access_token"]),
    )
    assert patch_resp.status_code == 404
