from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database import AuditLog, Intervention, PaymentEvent, RecoveryCase, RecoveryStatus
from services.diagnosis_service import diagnose_payment_failure


def _event_time(payment_data: dict[str, Any], raw_payload: dict[str, Any]) -> datetime:
    timestamp = payment_data.get("created_at") or raw_payload.get("created_at")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _find_case(db: Session, payment_id: str | None, order_id: str | None) -> RecoveryCase | None:
    conditions = []
    if payment_id:
        conditions.append(RecoveryCase.payment_id == payment_id)
    if order_id:
        conditions.append(RecoveryCase.order_id == order_id)
    if not conditions:
        return None
    return db.scalar(select(RecoveryCase).where(or_(*conditions)).order_by(RecoveryCase.opened_at.desc()))


def _new_event(
    event_id: str,
    event_type: str,
    payment_data: dict[str, Any],
    raw_payload: dict[str, Any],
) -> PaymentEvent:
    normalized = {
        key: payment_data.get(key)
        for key in (
            "id", "order_id", "amount", "currency", "method", "error_code",
            "error_source", "error_step", "error_reason", "error_description",
        )
    }
    return PaymentEvent(
        event_id=event_id,
        event_type=event_type,
        payment_id=payment_data.get("id"),
        order_id=payment_data.get("order_id"),
        amount=payment_data.get("amount"),
        currency=payment_data.get("currency"),
        payment_method=payment_data.get("method"),
        error_code=payment_data.get("error_code"),
        error_source=payment_data.get("error_source"),
        error_step=payment_data.get("error_step"),
        error_reason=payment_data.get("error_reason"),
        error_description=payment_data.get("error_description"),
        normalized_payload=normalized,
        raw_payload=raw_payload,
        occurred_at=_event_time(payment_data, raw_payload),
    )


def process_failed_payment(
    db: Session,
    event_id: str,
    event_type: str,
    payment_data: dict[str, Any],
    raw_payload: dict[str, Any],
) -> RecoveryCase:
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == event_id))
    if existing:
        case = existing.recovery_case
        if case is None:
            raise ValueError("Duplicate failed event is not linked to a recovery case")
        return case

    try:
        event = _new_event(event_id, event_type, payment_data, raw_payload)
        db.add(event)
        db.flush()

        case = _find_case(db, event.payment_id, event.order_id)
        if case is None:
            case = RecoveryCase(
                payment_id=event.payment_id,
                order_id=event.order_id,
                amount=event.amount or 0,
                currency=event.currency or "INR",
                status=RecoveryStatus.DETECTED,
            )
            db.add(case)
            db.flush()
            db.add(AuditLog(
                recovery_case_id=case.id,
                payment_event_id=event.id,
                action="CASE_CREATED",
                actor="SYSTEM",
                previous_status=None,
                new_status=RecoveryStatus.DETECTED,
            ))

        event.recovery_case = case
        decision = diagnose_payment_failure(payment_data)
        previous_status = case.status
        case.diagnosis = decision["diagnosis"]
        case.recommended_action = decision["recommended_action"]
        case.status = RecoveryStatus(decision["status"])
        db.add(AuditLog(
            recovery_case_id=case.id,
            payment_event_id=event.id,
            action="PAYMENT_DIAGNOSED",
            actor="SYSTEM",
            previous_status=previous_status,
            new_status=case.status,
            decision_data={"recommended_action": case.recommended_action},
        ))
        db.commit()
        db.refresh(case)
        return case
    except Exception:
        db.rollback()
        raise


def process_successful_payment(
    db: Session,
    event_id: str,
    event_type: str,
    payment_data: dict[str, Any],
    raw_payload: dict[str, Any],
) -> RecoveryCase | None:
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == event_id))
    if existing:
        return existing.recovery_case

    try:
        event = _new_event(event_id, event_type, payment_data, raw_payload)
        db.add(event)
        db.flush()
        case = _find_case(db, event.payment_id, event.order_id)
        if case is None:
            db.commit()
            return None

        event.recovery_case = case
        if case.status == RecoveryStatus.RECOVERED:
            db.commit()
            return case

        previous_status = case.status
        now = datetime.now(timezone.utc)
        case.status = RecoveryStatus.RECOVERED
        case.closed_at = now
        pending = db.scalars(select(Intervention).where(
            Intervention.recovery_case_id == case.id,
            Intervention.executed_at.is_(None),
            Intervention.cancelled_at.is_(None),
        )).all()
        for intervention in pending:
            intervention.cancelled_at = now
        db.add(AuditLog(
            recovery_case_id=case.id,
            payment_event_id=event.id,
            action="PAYMENT_RECOVERED",
            actor="SYSTEM",
            previous_status=previous_status,
            new_status=RecoveryStatus.RECOVERED,
            decision_data={"cancelled_interventions": len(pending)},
            policy_checks={"stopping_rule_applied": True},
        ))
        db.commit()
        db.refresh(case)
        return case
    except Exception:
        db.rollback()
        raise
