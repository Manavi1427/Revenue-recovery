from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from database import AuditLog, Intervention, RecoveryCase, RecoveryStatus
from integrations.payment_link_provider import PaymentLinkProviderError
from services.execution_service import (
    ExecutionConflict, ExecutionProviderFailure, ExecutionValidationError,
    execute_intervention,
)
from services.case_service import process_successful_payment


def scheduled(db, *, status=RecoveryStatus.ACTION_SCHEDULED, action="IMMEDIATE_RETRY", amount=12500, currency="INR", cancelled=False):
    case = RecoveryCase(
        payment_id=f"pay_exec_{status.value}_{action}_{amount}", amount=amount,
        currency=currency, status=status, recoverability_score=0.8,
    )
    db.add(case)
    db.flush()
    intervention = Intervention(
        recovery_case_id=case.id, action_type=action, channel="PENDING",
        scheduled_at=datetime.now(timezone.utc),
        cancelled_at=datetime.now(timezone.utc) if cancelled else None,
        action_payload={"status": "PENDING_EXECUTION", "decision_version": "bounded-rules-v1", "policy_version": "recovery-policy-v1"},
    )
    db.add(intervention)
    db.commit()
    return case, intervention


def test_mock_execution_persists_preview_transitions_and_is_idempotent(db, monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    monkeypatch.setenv("BACKEND_PUBLIC_URL", "http://testserver")
    case, intervention = scheduled(db)
    first = execute_intervention(db, intervention.id)
    repeated = execute_intervention(db, intervention.id)

    assert first.case_status == RecoveryStatus.CONTACTED
    assert first.payment_link.payment_link_id == repeated.payment_link.payment_link_id
    assert first.message == repeated.message
    assert not first.idempotent_replay and repeated.idempotent_replay
    db.refresh(intervention)
    assert intervention.executed_at is not None
    assert intervention.successful is True
    assert set(intervention.result_payload) == {"execution_status", "provider", "message"}
    assert "secret" not in str(intervention.result_payload).lower()
    success_logs = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "INTERVENTION_EXECUTED"))
    assert success_logs == 1


@pytest.mark.parametrize("status", [
    RecoveryStatus.RECOVERED, RecoveryStatus.SUPPRESSED,
    RecoveryStatus.EXHAUSTED, RecoveryStatus.HUMAN_REVIEW,
])
def test_restricted_case_statuses_cannot_execute(db, status):
    _, intervention = scheduled(db, status=status)
    with pytest.raises(ExecutionConflict):
        execute_intervention(db, intervention.id)


@pytest.mark.parametrize("action", ["HUMAN_REVIEW", "STOP_CASE"])
def test_non_executable_actions_and_cancelled_interventions_are_blocked(db, action):
    _, intervention = scheduled(db, action=action)
    with pytest.raises(ExecutionConflict):
        execute_intervention(db, intervention.id)
    _, cancelled = scheduled(db, cancelled=True)
    with pytest.raises(ExecutionConflict):
        execute_intervention(db, cancelled.id)


def test_invalid_amount_and_currency_are_rejected(db):
    _, zero = scheduled(db, amount=0)
    with pytest.raises(ExecutionValidationError):
        execute_intervention(db, zero.id)
    _, unsupported = scheduled(db, currency="USD")
    with pytest.raises(ExecutionValidationError):
        execute_intervention(db, unsupported.id)


def test_provider_failure_is_sanitized_and_retryable(db, monkeypatch):
    class FailingProvider:
        def create_payment_link(self, request):
            raise PaymentLinkProviderError("raw provider detail must not persist")

    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    case, intervention = scheduled(db)
    with pytest.raises(ExecutionProviderFailure):
        execute_intervention(db, intervention.id, FailingProvider())
    db.refresh(case)
    db.refresh(intervention)
    assert case.status == RecoveryStatus.ACTION_SCHEDULED
    assert intervention.executed_at is None
    assert intervention.successful is False
    assert intervention.action_payload["status"] == "FAILED"
    assert "raw provider" not in str(intervention.result_payload)

    retried = execute_intervention(db, intervention.id)
    assert retried.case_status == RecoveryStatus.CONTACTED


def test_recovery_during_provider_call_stops_message_and_contact(db, monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    case, intervention = scheduled(db)

    class RecoveringProvider:
        def create_payment_link(self, request):
            from integrations.mock_payment_link import MockPaymentLinkProvider
            case.status = RecoveryStatus.RECOVERED
            db.commit()
            return MockPaymentLinkProvider("http://testserver").create_payment_link(request)

    with pytest.raises(ExecutionConflict):
        execute_intervention(db, intervention.id, RecoveringProvider())
    db.refresh(case)
    db.refresh(intervention)
    assert case.status == RecoveryStatus.RECOVERED
    assert intervention.cancelled_at is not None
    assert intervention.executed_at is None
    assert intervention.result_payload is None
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "EXECUTION_STOPPED")) == 1


def test_captured_payment_after_contact_recovers_and_blocks_execution(db, monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    case, intervention = scheduled(db)
    execute_intervention(db, intervention.id)
    recovered = process_successful_payment(
        db, "evt_captured_after_contact", "payment.captured",
        {"id": case.payment_id, "amount": case.amount, "currency": case.currency}, {},
    )
    assert recovered.status == RecoveryStatus.RECOVERED
    assert recovered.closed_at is not None
    with pytest.raises(ExecutionConflict):
        execute_intervention(db, intervention.id)
