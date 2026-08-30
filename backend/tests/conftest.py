"""
Shared pytest fixtures.

Tests run against an isolated in-memory SQLite database per test (via
StaticPool, so all connections in a test share the same in-memory DB),
never against the real Postgres configured in .env. The FastAPI
`get_db_session` dependency is overridden accordingly.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 - registers all models on Base.metadata
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def client(session_maker):
    async def _override_get_db_session():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db_session] = _override_get_db_session
    # Not using `with TestClient(app) as c:` on purpose — entering that
    # context triggers app.main's lifespan, which tries to create tables
    # against the *real* DATABASE_URL. That's caught and merely logged
    # there, but there's no reason to pay for a doomed connection attempt
    # on every test when the override below already gives us real tables.
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def register_payload():
    return {
        "email": "owner@example-restaurant.io",
        "password": "correct-horse-battery-staple",
        "first_name": "Ada",
        "last_name": "Owner",
        "restaurant_name": "Example Italian Restaurant",
        "restaurant_timezone": "America/New_York",
    }


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
