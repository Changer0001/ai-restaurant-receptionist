"""
Shared pytest fixtures.

Tests run against an isolated in-memory SQLite database per test (via
StaticPool, so all connections in a test share the same in-memory DB),
never against the real Postgres configured in .env. The FastAPI
`get_db_session` dependency is overridden accordingly.
"""

import uuid

import chromadb
import pytest
import pytest_asyncio
from chromadb.config import Settings as ChromaSettings
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 - registers all models on Base.metadata
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.providers.embedding import get_embedding_provider
from app.rag.vector_db import VectorDB, get_vector_db
from tests.fakes import FakeEmbeddingProvider


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


@pytest_asyncio.fixture
async def db_session(session_maker):
    """A single AsyncSession for tests that talk to the ORM directly
    (rather than through the HTTP `client` fixture)."""
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def restaurant(db_session):
    """A persisted Restaurant row with a standard week of hours — for
    tests exercising the conversation engine, which needs a real
    Restaurant (name, timezone, phone/email for notifications) rather
    than just a restaurant_id string."""
    from app.db.models import Restaurant as RestaurantModel
    from app.db.models import RestaurantHours

    r = RestaurantModel(
        name="Test Bistro",
        timezone="America/New_York",
        phone_number="+15551234567",
        email="owner@testbistro.example",
        transfer_number="+15559876543",
        is_active=True,
    )
    db_session.add(r)
    await db_session.flush()

    for day in range(5):
        db_session.add(RestaurantHours(restaurant_id=r.id, day_of_week=day, opening_time="11:00", closing_time="22:00"))
    for day in (5, 6):
        db_session.add(RestaurantHours(restaurant_id=r.id, day_of_week=day, opening_time="12:00", closing_time="23:00"))

    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest.fixture
def vector_db():
    """A fresh, isolated in-memory ChromaDB instance per test — never the
    real chromadb Docker service configured in .env.

    Each test gets its own uniquely-named collection: chromadb's
    EphemeralClient caches its backing store keyed by client settings, so
    separate EphemeralClient() instances in the same process (i.e. two
    tests in the same pytest run) silently share data under the same
    default collection name unless given distinct names.
    """
    chroma_client = chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))
    return VectorDB(chroma_client, collection_name=f"test_{uuid.uuid4().hex}")


@pytest.fixture
def embedding_provider():
    return FakeEmbeddingProvider()


@pytest.fixture
def client(session_maker, vector_db, embedding_provider):
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
    app.dependency_overrides[get_vector_db] = lambda: vector_db
    app.dependency_overrides[get_embedding_provider] = lambda: embedding_provider
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
