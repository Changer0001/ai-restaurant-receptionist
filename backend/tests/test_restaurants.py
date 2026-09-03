"""Integration tests for restaurant CRUD and role enforcement."""

from tests.conftest import auth_headers


def _register(client, email, restaurant_name):
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "first_name": "Test",
        "last_name": "Owner",
        "restaurant_name": restaurant_name,
        "restaurant_timezone": "America/New_York",
    }
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_owner_can_read_own_restaurant(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.get(f"/api/restaurants/{me['restaurant_id']}", headers=auth_headers(tokens["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["name"] == register_payload["restaurant_name"]


def test_list_restaurants_returns_only_own_restaurant(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()

    resp = client.get("/api/restaurants", headers=auth_headers(tokens["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == register_payload["restaurant_name"]


def test_owner_can_patch_own_restaurant(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.patch(
        f"/api/restaurants/{me['restaurant_id']}",
        json={"transfer_number": "+12125551234", "ai_greeting": "Thanks for calling!"},
        headers=auth_headers(tokens["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transfer_number"] == "+12125551234"
    assert body["ai_greeting"] == "Thanks for calling!"
    # Unspecified fields are left untouched (PATCH semantics)
    assert body["name"] == register_payload["restaurant_name"]


def test_onboarding_settings_are_configurable_over_the_api(client, register_payload):
    """
    Everything that varies between clients is data reachable over the
    API. Onboarding a business must not need a code change, so its menu
    vocabulary and whether it takes bookings are settable here.
    """
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    fresh = client.get(
        f"/api/restaurants/{me['restaurant_id']}", headers=auth_headers(tokens["access_token"])
    ).json()
    # Unset until the restaurant chooses — see Restaurant in app/db/models.py.
    assert fresh["stt_vocabulary"] is None
    assert fresh["takes_reservations"] is None

    resp = client.patch(
        f"/api/restaurants/{me['restaurant_id']}",
        json={
            "stt_vocabulary": "carbonara, marinara, bruschetta, arancini",
            "takes_reservations": False,
        },
        headers=auth_headers(tokens["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stt_vocabulary"] == "carbonara, marinara, bruschetta, arancini"
    assert body["takes_reservations"] is False


def test_an_unknown_field_is_rejected_rather_than_silently_dropped(client, register_payload):
    """
    Pydantic's default is to ignore unknown keys, so a client PATCHing a
    field the running server is too old to have would get a clean 200
    for a request that stored nothing. That happened for real: a seeding
    script reported "OK" for a vocabulary the backend had discarded, and
    the bad-sounding call afterwards looked like a speech-recognition
    problem rather than a server that hadn't been restarted.
    """
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.patch(
        f"/api/restaurants/{me['restaurant_id']}",
        json={"stt_vocabluary": "typo in the field name"},
        headers=auth_headers(tokens["access_token"]),
    )
    assert resp.status_code == 422


def test_cross_tenant_read_is_404_not_403(client, register_payload):
    """
    Restaurant A's owner must not be able to see Restaurant B's data —
    and the response must not even confirm B exists (404, not 403).
    """
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")

    me_b = client.get("/api/auth/me", headers=auth_headers(tokens_b["access_token"])).json()

    resp = client.get(
        f"/api/restaurants/{me_b['restaurant_id']}",
        headers=auth_headers(tokens_a["access_token"]),
    )
    assert resp.status_code == 404


def test_cross_tenant_patch_is_blocked(client, register_payload):
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")
    me_b = client.get("/api/auth/me", headers=auth_headers(tokens_b["access_token"])).json()

    resp = client.patch(
        f"/api/restaurants/{me_b['restaurant_id']}",
        json={"name": "Hijacked Name"},
        headers=auth_headers(tokens_a["access_token"]),
    )
    assert resp.status_code == 404

    # Restaurant B's data is provably untouched
    unaffected = client.get(
        f"/api/restaurants/{me_b['restaurant_id']}", headers=auth_headers(tokens_b["access_token"])
    )
    assert unaffected.json()["name"] == "Restaurant B"


def test_unauthenticated_request_is_401(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.get(f"/api/restaurants/{me['restaurant_id']}")
    assert resp.status_code == 401
