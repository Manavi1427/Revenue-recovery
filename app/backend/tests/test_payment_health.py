from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database import AuditLog, PaymentEvent, RecoveryCase, RecoveryStatus, Intervention
from payment_health_config import PaymentHealthConfigurationError, PaymentHealthSettings, get_payment_health_settings
from services.payment_health_service import evaluate_method_health, get_payment_health
from services.evaluation_service import evaluate_recovery_case
from services.execution_service import ExecutionConflict, execute_intervention
from services.policy_service import apply_payment_health_policy
from services.recovery_actions import RecoveryAction


def _event(event_id, payment_id, method, event_type="payment.failed", *, batch="batch-a", hours_ago=1):
    return PaymentEvent(
        event_id=event_id, payment_id=payment_id, payment_method=method,
        event_type=event_type, batch_id=batch, amount=10_000, currency="INR",
        normalized_payload={}, raw_payload={},
        occurred_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


def _settings(minimum=10, baselines=None):
    return PaymentHealthSettings(True, 0.10, minimum, 24, baselines or {"upi": 0.08})


def test_failure_rate_uses_distinct_logical_attempts(db):
    db.add_all([
        _event("failed-1", "pay-1", "upi"),
        _event("captured-recovery", "pay-1", "upi", "payment.captured"),
        _event("success-2", "pay-2", "upi", "payment.captured"),
    ])
    db.commit()
    result = get_payment_health(db)["methods"][0]
    assert result["total_attempts"] == 2
    assert result["failed_attempts"] == 1
    assert result["observed_failure_rate"] == 0.5


def test_batch_and_time_window_boundaries(db):
    db.add_all([
        _event("a", "a", "upi", batch="batch-a"),
        _event("b", "b", "upi", batch="batch-b"),
        _event("old", "old", "upi", batch=None, hours_ago=30),
    ])
    db.add_all([
        RecoveryCase(amount=100, currency="INR", status=RecoveryStatus.DIAGNOSED,
                     batch_id=name) for name in ("batch-a", "batch-b")
    ])
    db.commit()
    assert get_payment_health(db, "batch-a")["methods"][0]["total_attempts"] == 1
    assert get_payment_health(db)["methods"][0]["total_attempts"] == 2


def test_health_threshold_is_strictly_greater():
    degraded = evaluate_method_health("upi", 100, 19, _settings())
    equal = evaluate_method_health("upi", 100, 18, _settings())
    healthy = evaluate_method_health("upi", 100, 17, _settings())
    assert degraded["status"] == "DEGRADED"
    assert equal["status"] == "HEALTHY"
    assert healthy["status"] == "HEALTHY"


def test_insufficient_data_and_no_baseline():
    assert evaluate_method_health("upi", 9, 9, _settings())["status"] == "INSUFFICIENT_DATA"
    assert evaluate_method_health("crypto", 100, 100, _settings())["status"] == "NO_BASELINE"


def test_empty_data_is_safe_and_read_only(db):
    before = len(db.query(AuditLog).all())
    result = get_payment_health(db)
    assert result["overall_status"] == "INSUFFICIENT_DATA"
    assert all(item["status"] == "INSUFFICIENT_DATA" for item in result["methods"])
    assert len(db.query(AuditLog).all()) == before


def test_invalid_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("PAYMENT_HEALTH_BASELINE_UPI", "1.5")
    with pytest.raises(PaymentHealthConfigurationError):
        get_payment_health_settings()


def test_default_batch_reliably_degrades_upi(db, monkeypatch):
    from schemas import DemoBatchRequest
    from services.demo_batch_service import run_demo_batch

    monkeypatch.setenv("DEMO_BATCH_ENABLED", "true")
    result = run_demo_batch(db, DemoBatchRequest(
        seed=42, batch_size=100, idempotency_key="health-default"
    ))
    health = get_payment_health(db, str(result["batch_id"]))
    upi = next(item for item in health["methods"] if item["payment_method"] == "upi")
    card = next(item for item in health["methods"] if item["payment_method"] == "card")
    assert upi["status"] == "DEGRADED"
    assert upi["observed_failure_rate"] > upi["degradation_limit"]
    assert upi["recommended_action"] == "SUGGEST_ALTERNATIVE_METHOD"
    assert card["status"] == "HEALTHY"
    assert health["simulated"] is True


def test_endpoint_returns_safe_statuses(client, db):
    response = client.get("/metrics/payment-health")
    missing = client.get("/metrics/payment-health?batch_id=missing")
    assert response.status_code == 200
    assert missing.status_code == 404


def _degraded_upi_traffic(db, batch="policy-batch"):
    events = [
        _event(f"fail-{i}", f"pay-fail-{i}", "upi", batch=batch)
        for i in range(3)
    ] + [
        _event(f"ok-{i}", f"pay-ok-{i}", "upi", "payment.captured", batch=batch)
        for i in range(7)
    ]
    db.add_all(events)
    db.flush()
    return events


def test_degraded_retry_is_replaced_and_audited(db):
    events = _degraded_upi_traffic(db)
    case = RecoveryCase(
        payment_id=events[0].payment_id, payment_method="upi", amount=10_000,
        currency="INR", status=RecoveryStatus.DIAGNOSED,
        diagnosis="Customer entered an incorrect PIN", recoverability_score=0.8,
        recommended_action="IMMEDIATE_RETRY", batch_id="policy-batch",
        experiment_group="TREATMENT",
    )
    db.add(case)
    db.flush()
    events[0].recovery_case_id = case.id
    db.commit()
    result = evaluate_recovery_case(db, case.id)
    assert result.decision.selected_action == RecoveryAction.SUGGEST_ALTERNATIVE_METHOD
    assert result.intervention.action_type == "SUGGEST_ALTERNATIVE_METHOD"
    actions = set(db.scalars(select(AuditLog.action).where(
        AuditLog.recovery_case_id == case.id
    )).all())
    assert "INTERVENTION_SUPPRESSED_METHOD_DEGRADED" in actions
    assert "ALTERNATIVE_METHOD_RECOMMENDED" in actions


def test_healthy_and_terminal_policy_priorities_are_preserved():
    healthy = apply_payment_health_policy(RecoveryAction.RETRY_LATER, "HEALTHY")
    stopped = apply_payment_health_policy(RecoveryAction.STOP_CASE, "DEGRADED")
    assert healthy.final_action == RecoveryAction.RETRY_LATER
    assert healthy.affected is False
    assert stopped.final_action == RecoveryAction.STOP_CASE
    assert stopped.affected is False


def test_holdout_evaluation_cannot_schedule_intervention(db):
    events = _degraded_upi_traffic(db, "holdout-batch")
    case = RecoveryCase(
        payment_id=events[0].payment_id, payment_method="upi", amount=10_000,
        currency="INR", status=RecoveryStatus.DIAGNOSED,
        diagnosis="Customer entered an incorrect PIN", recoverability_score=0.8,
        recommended_action="IMMEDIATE_RETRY", batch_id="holdout-batch",
        experiment_group="HOLDOUT",
    )
    db.add(case)
    db.flush()
    events[0].recovery_case_id = case.id
    db.commit()
    result = evaluate_recovery_case(db, case.id)
    assert result.policy.allowed is False
    assert result.intervention is None
    assert "Holdout" in result.policy.denial_reason


def test_execution_recheck_stops_stale_same_method_retry(db):
    _degraded_upi_traffic(db, "execution-health")
    case = RecoveryCase(
        payment_id="stale", payment_method="upi", amount=10_000, currency="INR",
        status=RecoveryStatus.ACTION_SCHEDULED, recoverability_score=0.8,
        batch_id="execution-health", experiment_group="TREATMENT",
    )
    intervention = Intervention(
        recovery_case=case, action_type="RETRY_LATER", channel="PENDING",
        scheduled_at=datetime.now(timezone.utc),
        action_payload={"status": "PENDING_EXECUTION"},
    )
    db.add_all([case, intervention])
    db.commit()
    with pytest.raises(ExecutionConflict, match="degraded"):
        execute_intervention(db, intervention.id)
    db.refresh(case)
    db.refresh(intervention)
    assert case.status == RecoveryStatus.SUPPRESSED
    assert intervention.cancelled_at is not None
    assert intervention.executed_at is None
