from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PythonEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for model defaults."""

    return datetime.now(timezone.utc)


def new_id() -> str:
    """Generate a portable UUID string primary key."""

    return str(uuid4())


class Base(DeclarativeBase):
    """Base class inherited by all RecoverIQ database models."""


class RecoveryStatus(str, PythonEnum):
    """Allowed lifecycle states for a revenue-recovery case."""

    DETECTED = "DETECTED"
    DIAGNOSED = "DIAGNOSED"
    ACTION_SCHEDULED = "ACTION_SCHEDULED"
    CONTACTED = "CONTACTED"
    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    SUPPRESSED = "SUPPRESSED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


recovery_status_type = Enum(
    RecoveryStatus,
    name="recovery_status",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)


class RecoveryCase(Base):
    """A payment or order whose revenue is being recovered."""

    __tablename__ = "recovery_cases"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_recovery_cases_amount_nonnegative"),
        CheckConstraint(
            "recoverability_score IS NULL OR "
            "(recoverability_score >= 0 AND recoverability_score <= 1)",
            name="ck_recovery_cases_score_range",
        ),
        Index("ix_recovery_cases_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    payment_id: Mapped[str | None] = mapped_column(
        String(100), index=True, nullable=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(100), index=True, nullable=True
    )

    # Store monetary amounts in the smallest currency unit (for example, paise).
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    recoverability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    status: Mapped[RecoveryStatus] = mapped_column(
        recovery_status_type,
        default=RecoveryStatus.DETECTED,
        nullable=False,
        index=True,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    payment_events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="recovery_case",
    )
    interventions: Mapped[list[Intervention]] = relationship(
        back_populates="recovery_case",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="recovery_case",
        cascade="all, delete-orphan",
    )


class PaymentEvent(Base):
    """A normalized Razorpay webhook event retained for idempotent processing."""

    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_payment_events_amount_nonnegative",
        ),
        Index("ix_payment_events_payment_occurred", "payment_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )

    # Unique event_id prevents the same webhook from being processed twice.
    event_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    payment_id: Mapped[str | None] = mapped_column(
        String(100), index=True, nullable=True
    )
    order_id: Mapped[str | None] = mapped_column(
        String(100), index=True, nullable=True
    )
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(150), nullable=True)
    error_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    normalized_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    recovery_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    recovery_case: Mapped[RecoveryCase | None] = relationship(
        back_populates="payment_events"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="payment_event"
    )


class Intervention(Base):
    """A recovery action that was scheduled, executed, cancelled, or completed."""

    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint(
            "cost IS NULL OR cost >= 0",
            name="ck_interventions_cost_nonnegative",
        ),
        Index(
            "ix_interventions_case_scheduled_at",
            "recovery_case_id",
            "scheduled_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    recovery_case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    successful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    recovery_case: Mapped[RecoveryCase] = relationship(
        back_populates="interventions"
    )


class AuditLog(Base):
    """An append-only record of decisions, policy checks, and state changes."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_case_created_at", "recovery_case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_id
    )
    recovery_case_id: Mapped[str] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    payment_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_events.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(
        String(50), default="SYSTEM", nullable=False
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    previous_status: Mapped[RecoveryStatus | None] = mapped_column(
        Enum(
            RecoveryStatus,
            name="ck_audit_logs_previous_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    new_status: Mapped[RecoveryStatus | None] = mapped_column(
        Enum(
            RecoveryStatus,
            name="ck_audit_logs_new_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    decision_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    policy_checks: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    recovery_case: Mapped[RecoveryCase] = relationship(
        back_populates="audit_logs"
    )
    payment_event: Mapped[PaymentEvent | None] = relationship(
        back_populates="audit_logs"
    )
