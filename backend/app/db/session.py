"""
Database Session Management

Provides async SQLAlchemy session factory and session management utilities.
"""

from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Build engine kwargs conditionally: pool_size/max_overflow are QueuePool
# options and SQLAlchemy raises a TypeError if they're passed alongside
# NullPool (which we use in development to avoid stale connections across
# --reload restarts).
_engine_kwargs: dict[str, Any] = {
    "echo": settings.DATABASE_ECHO,
    "connect_args": {
        "server_settings": {
            "application_name": "ai_restaurant_receptionist",
        }
    },
}

if settings.IS_DEVELOPMENT:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW

# Create async engine
engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting an async database session.

    Usage in FastAPI route:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
