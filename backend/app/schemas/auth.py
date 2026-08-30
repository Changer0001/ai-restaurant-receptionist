"""Authentication request/response schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """
    Self-service sign-up: creates a brand-new Restaurant and its first
    User (role=restaurant_owner) in one transaction. This is the only
    way a Restaurant is created in the MVP — there is no separate
    POST /api/restaurants, since every restaurant needs an owner.

    Platform admin accounts are not created through this public endpoint;
    see scripts/create_platform_admin.py.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    restaurant_name: str = Field(min_length=1, max_length=255)
    restaurant_timezone: str = Field(default="America/New_York", max_length=50)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserRead(BaseModel):
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: str
    restaurant_id: Optional[str]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
