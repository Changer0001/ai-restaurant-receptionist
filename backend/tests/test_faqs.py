"""Integration tests for FAQ CRUD and tenant/role enforcement."""

from tests.conftest import auth_headers


def _register(client, email, restaurant_name):
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "restaurant_name": restaurant_name,
        "restaurant_timezone": "America/New_York",
    }
    return client.post("/api/auth/register", json=payload).json()


def test_create_and_list_faq(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    create_resp = client.post(
        f"/api/restaurants/{rid}/faqs",
        json={"question": "Do you have outdoor seating?", "answer": "Yes, we have a patio.", "category": "seating"},
        headers=auth_headers(tokens["access_token"]),
    )
    assert create_resp.status_code == 201
    faq = create_resp.json()
    assert faq["question"] == "Do you have outdoor seating?"
    assert faq["restaurant_id"] == rid

    list_resp = client.get(f"/api/restaurants/{rid}/faqs", headers=auth_headers(tokens["access_token"]))
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_update_faq(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    faq = client.post(
        f"/api/restaurants/{rid}/faqs",
        json={"question": "What are your hours?", "answer": "9-5"},
        headers=auth_headers(tokens["access_token"]),
    ).json()

    resp = client.patch(
        f"/api/restaurants/{rid}/faqs/{faq['id']}",
        json={"answer": "Mon-Fri 11am-10pm, Sat-Sun 12pm-11pm"},
        headers=auth_headers(tokens["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Mon-Fri 11am-10pm, Sat-Sun 12pm-11pm"
    assert resp.json()["question"] == "What are your hours?"  # untouched


def test_delete_faq(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    faq = client.post(
        f"/api/restaurants/{rid}/faqs",
        json={"question": "Delete me", "answer": "..."},
        headers=auth_headers(tokens["access_token"]),
    ).json()

    delete_resp = client.delete(
        f"/api/restaurants/{rid}/faqs/{faq['id']}", headers=auth_headers(tokens["access_token"])
    )
    assert delete_resp.status_code == 204

    list_resp = client.get(f"/api/restaurants/{rid}/faqs", headers=auth_headers(tokens["access_token"]))
    assert list_resp.json() == []


def test_cannot_access_or_mutate_another_restaurants_faq(client, register_payload):
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    me_a = client.get("/api/auth/me", headers=auth_headers(tokens_a["access_token"])).json()

    faq_a = client.post(
        f"/api/restaurants/{me_a['restaurant_id']}/faqs",
        json={"question": "A's secret FAQ", "answer": "..."},
        headers=auth_headers(tokens_a["access_token"]),
    ).json()

    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")

    # B cannot even list A's FAQs (tenant path check blocks it)
    resp = client.get(
        f"/api/restaurants/{me_a['restaurant_id']}/faqs", headers=auth_headers(tokens_b["access_token"])
    )
    assert resp.status_code == 404

    # B cannot delete A's FAQ by guessing the restaurant_id in the path
    delete_resp = client.delete(
        f"/api/restaurants/{me_a['restaurant_id']}/faqs/{faq_a['id']}",
        headers=auth_headers(tokens_b["access_token"]),
    )
    assert delete_resp.status_code == 404

    # A's FAQ is provably still there
    still_there = client.get(
        f"/api/restaurants/{me_a['restaurant_id']}/faqs", headers=auth_headers(tokens_a["access_token"])
    )
    assert len(still_there.json()) == 1
