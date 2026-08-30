from sqlalchemy import func, select

from database import AuditLog, Intervention, PaymentEvent, RecoveryCase, RecoveryStatus
from services.case_service import process_failed_payment, process_successful_payment


def failed_payment():
    return {
        "id": "pay_1", "order_id": "order_1", "amount": 249900,
        "currency": "INR", "method": "card", "error_reason": "incorrect_pin",
        "created_at": 1788050000,
    }


def test_failed_event_is_atomic_and_idempotent(db):
    payment = failed_payment()
    case = process_failed_payment(db, "evt_failed_1", "payment.failed", payment, {"event": "payment.failed"})
    duplicate = process_failed_payment(db, "evt_failed_1", "payment.failed", payment, {"event": "payment.failed"})

    assert duplicate.id == case.id
    assert case.status == RecoveryStatus.DIAGNOSED
    assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
    assert db.scalar(select(func.count()).select_from(RecoveryCase)) == 1
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()
    assert [log.action for log in logs] == ["CASE_CREATED", "PAYMENT_DIAGNOSED"]
    assert logs[0].previous_status is None
    assert logs[0].new_status == RecoveryStatus.DETECTED


def test_unknown_failure_goes_to_human_review(db):
    payment = {**failed_payment(), "id": "pay_unknown", "error_reason": "mystery"}
    case = process_failed_payment(db, "evt_unknown", "payment.failed", payment, {})
    assert case.status == RecoveryStatus.HUMAN_REVIEW


def test_success_recovers_and_applies_stopping_rule(db):
    case = process_failed_payment(db, "evt_failed_1", "payment.failed", failed_payment(), {})
    intervention = Intervention(recovery_case_id=case.id, action_type="RETRY")
    db.add(intervention)
    db.commit()
    success = {"id": "pay_1", "order_id": "order_1", "amount": 249900, "currency": "INR"}

    recovered = process_successful_payment(db, "evt_success_1", "payment.captured", success, {})
    repeated = process_successful_payment(db, "evt_success_1", "payment.captured", success, {})

    assert recovered.status == RecoveryStatus.RECOVERED
    assert recovered.closed_at is not None
    assert repeated.id == recovered.id
    db.refresh(intervention)
    assert intervention.cancelled_at is not None
    recovery_logs = db.scalars(select(AuditLog).where(AuditLog.action == "PAYMENT_RECOVERED")).all()
    assert len(recovery_logs) == 1
    assert recovery_logs[0].decision_data["cancelled_interventions"] == 1
    assert recovery_logs[0].policy_checks["stopping_rule_applied"] is True


def test_unmatched_success_is_stored(db):
    result = process_successful_payment(db, "evt_success_orphan", "payment.captured", {"id": "pay_none"}, {})
    assert result is None
    assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
