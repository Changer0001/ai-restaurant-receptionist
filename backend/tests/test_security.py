"""Unit tests for password hashing and JWT handling."""

import pytest
from jose import JWTError

from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_plaintext():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert hashed.startswith("$2b$")


def test_verify_password_correct():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_password_incorrect():
    hashed = hash_password("hunter2")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_is_salted_differently_each_time():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
    assert verify_password("same-password", h1)
    assert verify_password("same-password", h2)


def test_access_token_roundtrip_carries_role_and_restaurant():
    token = create_access_token("user-1", "restaurant_owner", "restaurant-9")
    payload = decode_token(token, TokenType.ACCESS)
    assert payload.user_id == "user-1"
    assert payload.role == "restaurant_owner"
    assert payload.restaurant_id == "restaurant-9"


def test_refresh_token_cannot_be_used_as_access_token():
    refresh = create_refresh_token("user-1")
    with pytest.raises(JWTError):
        decode_token(refresh, TokenType.ACCESS)


def test_access_token_cannot_be_used_as_refresh_token():
    access = create_access_token("user-1", "restaurant_staff", None)
    with pytest.raises(JWTError):
        decode_token(access, TokenType.REFRESH)


def test_garbage_token_is_rejected():
    with pytest.raises(JWTError):
        decode_token("not-a-real-jwt", TokenType.ACCESS)
