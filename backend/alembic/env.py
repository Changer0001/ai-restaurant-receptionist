"""
Alembic Environment Configuration

Configured for async SQLAlchemy (asyncpg). Migrations run via
`connection.run_sync(...)`, following the standard Alembic async recipe.

The database URL always comes from application settings (DATABASE_URL
env var / .env), never hardcoded here — this keeps a single source of
truth between the running app and its migrations.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the app's settings and metadata
from app.core.config import settings
from app.db import models  # noqa: F401 - registers all model classes on Base.metadata
from app.db.base import Base

# Alembic Config object, provides access to values in alembic.ini
config = context.config

# Inject the real database URL from application settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for logging (unless called programmatically)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata used for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    so no DBAPI connection is required. Calls to context.execute()
    emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and run migrations against a live sync connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create an Engine and associate a connection with the context,
    running the actual migration in a sync callback via run_sync.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
