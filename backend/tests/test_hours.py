"""Integration tests for restaurant operating-hours management."""

from tests.conftest import auth_headers


def test_put_hours_replaces_full_week(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    weekly = {
        "hours": [
            {"day_of_week": d, "opening_time": "11:00", "closing_time": "22:00", "is_closed": False}
            for d in range(5)
        ]
        + [
            {"day_of_week": 5, "opening_time": "12:00", "closing_time": "23:00", "is_closed": False},
            {"day_of_week": 6, "opening_time": "12:00", "closing_time": "23:00", "is_closed": False},
        ]
    }

    resp = client.put(
        f"/api/restaurants/{rid}/hours", json=weekly, headers=auth_headers(tokens["access_token"])
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 7

    get_resp = client.get(f"/api/restaurants/{rid}/hours", headers=auth_headers(tokens["access_token"]))
    assert len(get_resp.json()) == 7
    monday = next(h for h in get_resp.json() if h["day_of_week"] == 0)
    assert monday["opening_time"] == "11:00"
    assert monday["closing_time"] == "22:00"


def test_put_hours_is_idempotent_replace_not_append(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]
    headers = auth_headers(tokens["access_token"])

    first = {"hours": [{"day_of_week": 0, "opening_time": "09:00", "closing_time": "17:00", "is_closed": False}]}
    client.put(f"/api/restaurants/{rid}/hours", json=first, headers=headers)

    second = {"hours": [{"day_of_week": 0, "opening_time": "10:00", "closing_time": "18:00", "is_closed": False}]}
    resp = client.put(f"/api/restaurants/{rid}/hours", json=second, headers=headers)

    assert resp.status_code == 200
    # Must not accumulate rows across PUTs
    assert len(resp.json()) == 1
    assert resp.json()[0]["opening_time"] == "10:00"


def test_invalid_time_format_rejected(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    bad = {"hours": [{"day_of_week": 0, "opening_time": "9am", "closing_time": "17:00", "is_closed": False}]}
    resp = client.put(
        f"/api/restaurants/{rid}/hours", json=bad, headers=auth_headers(tokens["access_token"])
    )
    assert resp.status_code == 422


def test_duplicate_day_of_week_rejected(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    dupes = {
        "hours": [
            {"day_of_week": 0, "opening_time": "09:00", "closing_time": "17:00", "is_closed": False},
            {"day_of_week": 0, "opening_time": "10:00", "closing_time": "18:00", "is_closed": False},
        ]
    }
    resp = client.put(
        f"/api/restaurants/{rid}/hours", json=dupes, headers=auth_headers(tokens["access_token"])
    )
    assert resp.status_code == 422
