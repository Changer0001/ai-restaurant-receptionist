"""
Database Base Classes and Common Models

Provides base models and mixins for all database models.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

Base = declarative_base()


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUID primary key."""

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        nullable=False,
    )


class TenantMixin:
    """Mixin that adds tenant_id for multi-tenancy."""

    restaurant_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )


# Base class with all common columns
class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Base model with UUID primary key and timestamps."""

    __abstract__ = True


class TenantModel(BaseModel, TenantMixin):
    """Base model for tenant-isolated resources."""

    __abstract__ = True
