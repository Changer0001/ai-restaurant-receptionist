"""
Database Base Classes and Common Models

Provides base models and mixins for all database models.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 typed declarative base.

    Subclassing DeclarativeBase (rather than the legacy declarative_base()
    factory function) is what lets mypy recognize `class BaseModel(Base, ...)`
    below as a valid base class without needing the separate sqlalchemy
    mypy plugin.
    """


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
    """Mixin that adds tenant_id for multi-tenancy.

    Every tenant-owned table gets a real foreign key constraint to
    restaurants.id, not just an unconstrained column — the database
    itself refuses to let a row point at a restaurant that doesn't
    exist, on top of the application-layer filtering by restaurant_id.
    """

    restaurant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("restaurants.id", name="fk_restaurant_id", ondelete="CASCADE"),
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
