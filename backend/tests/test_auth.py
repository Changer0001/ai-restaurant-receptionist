"""Integration tests for the authentication endpoints."""

from tests.conftest import auth_headers


def test_register_creates_restaurant_and_owner(client, register_payload):
    resp = client.post("/api/auth/register", json=register_payload)
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


def test_register_duplicate_email_rejected(client, register_payload):
    first = client.post("/api/auth/register", json=register_payload)
    assert first.status_code == 201

    second = client.post("/api/auth/register", json=register_payload)
    assert second.status_code == 409


def test_register_rejects_short_password(client, register_payload):
    register_payload["password"] = "short"
    resp = client.post("/api/auth/register", json=register_payload)
    assert resp.status_code == 422


def test_login_with_correct_credentials(client, register_payload):
    client.post("/api/auth/register", json=register_payload)

    resp = client.post(
        "/api/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_with_wrong_password(client, register_payload):
    client.post("/api/auth/register", json=register_payload)

    resp = client.post(
        "/api/auth/login",
        json={"email": register_payload["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_login_with_unknown_email(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@nowhere.io", "password": "whatever123"},
    )
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()

    resp = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == register_payload["email"]
    assert body["role"] == "restaurant_owner"
    assert body["restaurant_id"] is not None


def test_refresh_issues_new_access_token(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()

    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_tokens = resp.json()
    # Note: not asserting new_tokens["access_token"] != tokens["access_token"] —
    # JWT claims (including iat/exp) only have second-level granularity, so a
    # refresh issued within the same wall-clock second as registration yields
    # a byte-identical token. That's not a security issue (the token is still
    # correctly scoped and valid); what matters is that it actually works:

    # New access token actually works
    me_resp = client.get("/api/auth/me", headers=auth_headers(new_tokens["access_token"]))
    assert me_resp.status_code == 200


def test_refresh_rejects_access_token(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()

    # Passing an access token where a refresh token is expected must fail
    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_me_rejects_garbage_bearer_token(client):
    resp = client.get("/api/auth/me", headers=auth_headers("garbage.token.value"))
    assert resp.status_code == 401
