"""
AI Restaurant Receptionist - Main FastAPI Application

This is the entry point for the FastAPI backend. It initializes all services,
configures middleware, and defines routes.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_client import make_asgi_app
from sqlalchemy import text

from app.api import routes
from app.api.endpoints import twilio_webhooks
from app.core.cache import close_redis, init_redis
from app.core.config import settings
from app.db.base import Base
from app.db.session import async_session_maker, engine

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Manage application startup and shutdown events.
    """
    # Startup
    logger.info("Starting AI Restaurant Receptionist API")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info(f"Ollama: {settings.OLLAMA_BASE_URL}")
    logger.info(f"Vector DB: {settings.VECTOR_DB_URL}")

    # Create database tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")

    await init_redis()

    yield

    # Shutdown
    logger.info("Shutting down AI Restaurant Receptionist API")
    await close_redis()
    await engine.dispose()


# Create FastAPI application
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

# Add security middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# Health check endpoints
@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint for Docker health checks."""
    return {"status": "ok"}


@app.get("/ready", tags=["Health"])
async def readiness_check(response: Response):
    """
    Readiness check that verifies critical dependencies.
    Returns 503 if dependencies are unavailable.
    """
    checks = {}

    # Check database
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Check Redis
    try:
        from app.core.cache import redis_client

        if redis_client is None:
            raise RuntimeError("Redis client not initialized")
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Check Ollama
    try:
        from app.providers.llm.ollama_provider import OllamaLLMProvider

        provider = OllamaLLMProvider()
        # health_check() returns False on failure rather than raising, so
        # its result must be checked explicitly — catching exceptions alone
        # would silently report "ok" for an unreachable Ollama server.
        checks["ollama"] = "ok" if await provider.health_check() else "error: unreachable"
    except Exception as e:
        checks["ollama"] = f"error: {str(e)}"

    # Check Vector DB
    try:
        from app.rag.vector_db import get_vector_db

        vdb = await get_vector_db()
        checks["vector_db"] = "ok" if await vdb.health_check() else "error: unreachable"
    except Exception as e:
        checks["vector_db"] = f"error: {str(e)}"

    # Check SMTP (only if the notification worker would actually use it —
    # an operator running with email notifications administratively
    # disabled shouldn't have /ready flap on an SMTP server they never
    # configured)
    if settings.FEATURE_EMAIL_NOTIFICATIONS:
        try:
            from app.providers.email import get_email_provider

            email_provider = await get_email_provider()
            checks["smtp"] = "ok" if await email_provider.health_check() else "error: unreachable"
        except Exception as e:
            checks["smtp"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if all_ok else 503

    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Include API routes
app.include_router(routes.router, prefix=settings.API_V1_PREFIX)

# Twilio webhooks live outside /api — they're called by Twilio's
# platform directly, authenticated by X-Twilio-Signature rather than the
# JWT scheme the rest of the API uses, and match the exact webhook paths
# configured in Twilio's console / .env's WEBHOOK_BASE_PATH.
app.include_router(
    twilio_webhooks.router, prefix=f"{settings.WEBHOOK_BASE_PATH}/twilio", tags=["Twilio Webhooks"]
)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint - returns API information."""
    return {
        "name": settings.API_TITLE,
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
