"""Authentication endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db_session
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserRead
from app.services import auth_service

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Sign up a new restaurant and its owner account in one step."""
    return await auth_service.register_restaurant_owner(db, data)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    user = await auth_service.authenticate_user(db, data.email, data.password)
    return auth_service.issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    return await auth_service.refresh_access_token(db, data.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
