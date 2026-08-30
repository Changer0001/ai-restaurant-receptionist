"""
Database Models

SQLAlchemy ORM models for all domain entities.
Organized by logical domains.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    JSON,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import BaseModel, TenantModel


# ============================================================================
# ENUMS
# ============================================================================


class UserRoleEnum(str, Enum):
    """User role types."""
    PLATFORM_ADMIN = "platform_admin"
    RESTAURANT_OWNER = "restaurant_owner"
    RESTAURANT_MANAGER = "restaurant_manager"
    RESTAURANT_STAFF = "restaurant_staff"


class ReservationStatusEnum(str, Enum):
    """Reservation status types."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class CallOutcomeEnum(str, Enum):
    """Call outcome types."""
    FAQ_ANSWERED = "faq_answered"
    RESERVATION_CREATED = "reservation_created"
    CALL_TRANSFERRED = "call_transferred"
    HUMAN_ESCALATION = "human_escalation"
    CALL_ABANDONED = "call_abandoned"
    UNKNOWN = "unknown"


# ============================================================================
# TENANT / RESTAURANT MODELS
# ============================================================================


class Restaurant(BaseModel, __tablename__="restaurants"):
    """Restaurant entity - the primary tenant."""

    __tablename__ = "restaurants"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20))
    country: Mapped[Optional[str]] = mapped_column(String(100), default="US")
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    website: Mapped[Optional[str]] = mapped_column(String(500))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    transfer_number: Mapped[Optional[str]] = mapped_column(String(20))
    menu_url: Mapped[Optional[str]] = mapped_column(String(500))
    ai_greeting: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Relationships
    phone_numbers = relationship(
        "RestaurantPhoneNumber",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    hours = relationship(
        "RestaurantHours",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    faqs = relationship(
        "RestaurantFAQ",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    users = relationship(
        "User",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    reservations = relationship(
        "Reservation",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    calls = relationship(
        "Call",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    knowledge_docs = relationship(
        "RestaurantKnowledgeDocument",
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )


class RestaurantPhoneNumber(TenantModel, __tablename__="restaurant_phone_numbers"):
    """Maps Twilio phone numbers to restaurants."""

    __tablename__ = "restaurant_phone_numbers"

    phone_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
    )
    twilio_sid: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Foreign key
    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_phone_restaurant_id"),
        Index("idx_phone_restaurant_id", "restaurant_id"),
    )


class RestaurantHours(TenantModel, __tablename__="restaurant_hours"):
    """Operating hours for restaurants."""

    __tablename__ = "restaurant_hours"

    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    opening_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    closing_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    restaurant = relationship("Restaurant", back_populates="hours")

    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_hours_restaurant_id"),
        Index("idx_hours_restaurant_day", "restaurant_id", "day_of_week"),
        UniqueConstraint("restaurant_id", "day_of_week", name="uq_restaurant_day"),
    )


class RestaurantFAQ(TenantModel, __tablename__="restaurant_faqs"):
    """FAQ entries for restaurants."""

    __tablename__ = "restaurant_faqs"

    question: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Relationships
    restaurant = relationship("Restaurant", back_populates="faqs")

    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_faq_restaurant_id"),
        Index("idx_faq_restaurant_category", "restaurant_id", "category"),
    )


class RestaurantKnowledgeDocument(TenantModel, __tablename__="restaurant_knowledge_documents"):
    """Knowledge base documents for RAG."""

    __tablename__ = "restaurant_knowledge_documents"

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), index=True)  # menu, policy, etc.
    source: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    vector_ids: Mapped[Optional[list]] = mapped_column(JSON)  # ChromaDB IDs

    # Relationships
    restaurant = relationship("Restaurant", back_populates="knowledge_docs")

    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_doc_restaurant_id"),
        Index("idx_doc_restaurant_type", "restaurant_id", "document_type"),
    )


# ============================================================================
# USER & AUTH MODELS
# ============================================================================


class User(BaseModel, __tablename__="users"):
    """User accounts."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRoleEnum] = mapped_column(
        SQLEnum(UserRoleEnum),
        nullable=False,
        default=UserRoleEnum.RESTAURANT_STAFF,
        index=True,
    )
    restaurant_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("restaurants.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    restaurant = relationship("Restaurant", back_populates="users")

    __table_args__ = (
        Index("idx_user_email_active", "email", "is_active"),
        Index("idx_user_restaurant_active", "restaurant_id", "is_active"),
    )


# ============================================================================
# RESERVATION MODELS
# ============================================================================


class Reservation(TenantModel, __tablename__="reservations"):
    """Reservation requests."""

    __tablename__ = "reservations"

    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    reservation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reservation_time: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    special_notes: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[ReservationStatusEnum] = mapped_column(
        SQLEnum(ReservationStatusEnum),
        nullable=False,
        default=ReservationStatusEnum.PENDING,
        index=True,
    )
    call_sid: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    # Relationships
    restaurant = relationship("Restaurant", back_populates="reservations")

    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_reservation_restaurant_id"),
        Index("idx_reservation_restaurant_date", "restaurant_id", "reservation_date"),
        Index("idx_reservation_restaurant_status", "restaurant_id", "status"),
    )


# ============================================================================
# CALL MODELS
# ============================================================================


class Call(TenantModel, __tablename__="calls"):
    """Call records."""

    __tablename__ = "calls"

    call_sid: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    caller_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    called_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    outcome: Mapped[CallOutcomeEnum] = mapped_column(
        SQLEnum(CallOutcomeEnum),
        nullable=False,
        default=CallOutcomeEnum.UNKNOWN,
        index=True,
    )
    was_transferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    was_escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    recording_path: Mapped[Optional[str]] = mapped_column(String(500))
    metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    # Relationships
    restaurant = relationship("Restaurant", back_populates="calls")

    __table_args__ = (
        ForeignKey("restaurants.id", name="fk_call_restaurant_id"),
        Index("idx_call_restaurant_time", "restaurant_id", "start_time"),
        Index("idx_call_restaurant_outcome", "restaurant_id", "outcome"),
    )


class CallTranscript(TenantModel, __tablename__="call_transcripts"):
    """Detailed call transcripts (turn-by-turn)."""

    __tablename__ = "call_transcripts"

    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "caller" or "assistant"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float)  # STT confidence

    __table_args__ = (
        Index("idx_transcript_call_time", "call_id", "timestamp"),
    )


class CallEvent(TenantModel, __tablename__="call_events"):
    """Call state machine events for debugging/auditing."""

    __tablename__ = "call_events"

    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_data: Mapped[Optional[dict]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        Index("idx_event_call_time", "call_id", "timestamp"),
        Index("idx_event_type", "event_type"),
    )


# ============================================================================
# NOTIFICATION MODELS
# ============================================================================


class Notification(TenantModel, __tablename__="notifications"):
    """Notification history."""

    __tablename__ = "notifications"

    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # sms, email, etc.
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_notification_restaurant_sent", "restaurant_id", "is_sent"),
        Index("idx_notification_type", "notification_type"),
    )


# ============================================================================
# AUDIT / LOGGING MODELS
# ============================================================================


class AuditLog(TenantModel, __tablename__="audit_logs"):
    """Audit log for all user actions."""

    __tablename__ = "audit_logs"

    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    changes: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        Index("idx_audit_restaurant_time", "restaurant_id", "created_at"),
        Index("idx_audit_user_action", "user_id", "action"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
    )
