from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database import AuditLog, ExperimentGroup, Intervention, PaymentEvent, RecoveryCase, RecoveryStatus
from schemas import DemoBatchRequest
from services.demo_batch_service import (
    _case_specs,
    calculate_failure_counts,
    run_demo_batch,
)
from services.metrics_service import calculate_overview_metrics


def test_default_failure_distribution_is_exact():
    assert calculate_failure_counts(100) == {
        "incorrect_pin": 30,
        "insufficient_funds": 25,
        "bank_unavailable": 20,
        "expired_card": 15,
        "unknown_failure": 10,
    }


def test_scaled_distribution_always_adds_up():
    for size in (1, 7, 33, 101, 499):
        assert sum(calculate_failure_counts(size).values()) == size


def test_seed_reproduces_generated_values_but_batch_ids_stay_unique():
    request = DemoBatchRequest(seed=42, batch_size=20)
    first = _case_specs("batch-a", request)
    second = _case_specs("batch-a", request)
    other_seed = _case_specs("batch-a", DemoBatchRequest(seed=43, batch_size=20))
    assert [(x["failure"], x["amount"], x["method"]) for x in first] == [
        (x["failure"], x["amount"], x["method"]) for x in second
    ]
    assert [(x["amount"], x["method"]) for x in first] != [
        (x["amount"], x["method"]) for x in other_seed
    ]
    assert len({x["event_id"] for x in first}) == 20
    assert len({x["payment_id"] for x in first}) == 20
    assert _case_specs("batch-b", request)[0]["event_id"] != first[0]["event_id"]


def test_default_batch_persists_groups_and_uses_no_holdout_interventions(db, monkeypatch):
    monkeypatch.setenv("DEMO_BATCH_ENABLED", "true")
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    result = run_demo_batch(db, DemoBatchRequest(
        seed=42, batch_size=100, treatment_percent=80,
        idempotency_key="default-batch-test",
    ))
    cases = list(db.scalars(select(RecoveryCase).where(
        RecoveryCase.batch_id == result["batch_id"]
    )).all())
    assert len(cases) == 100
    assert result["treatment_cases"] == 72
    assert result["holdout_cases"] == 18
    assert result["ineligible_cases"] == 10
    unknown = [case for case in cases if case.experiment_group == ExperimentGroup.INELIGIBLE.value]
    assert len(unknown) == 10
    assert all(case.status == RecoveryStatus.HUMAN_REVIEW for case in unknown)
    holdout_ids = {case.id for case in cases if case.experiment_group == ExperimentGroup.HOLDOUT.value}
    assert db.scalars(select(Intervention).where(
        Intervention.recovery_case_id.in_(holdout_ids)
    )).all() == []
    assert len({event.event_id for event in db.scalars(select(PaymentEvent)).all()}) == len(
        db.scalars(select(PaymentEvent)).all()
    )
    treatment_ids = {case.id for case in cases if case.experiment_group == ExperimentGroup.TREATMENT.value}
    treatment_actions = set(db.scalars(select(AuditLog.action).where(
        AuditLog.recovery_case_id.in_(treatment_ids)
    )).all())
    assert "RECOVERY_SCORED" in treatment_actions
    assert "POLICY_EVALUATED" in treatment_actions
    assert "INTERVENTION_EXECUTION_STARTED" in treatment_actions
    holdout_actions = set(db.scalars(select(AuditLog.action).where(
        AuditLog.recovery_case_id.in_(holdout_ids)
    )).all())
    assert "EXPERIMENT_HOLDOUT_ASSIGNED" in holdout_actions
    assert "POLICY_EVALUATED" not in holdout_actions
    assert "PAYMENT_LINK_CREATED" not in holdout_actions
    assert result["simulated"] is True
    assert result["metrics"]["average_recovery_time_seconds"] >= 300


def test_batch_idempotency_returns_persisted_result(db, monkeypatch):
    monkeypatch.setenv("DEMO_BATCH_ENABLED", "true")
    request = DemoBatchRequest(
        seed=7, batch_size=10, treatment_percent=80,
        idempotency_key="replay-test",
    )
    first = run_demo_batch(db, request)
    count = len(db.scalars(select(RecoveryCase)).all())
    replay = run_demo_batch(db, request)
    assert replay["batch_id"] == first["batch_id"]
    assert replay["idempotent_replay"] is True
    assert len(db.scalars(select(RecoveryCase)).all()) == count


def test_amount_based_metrics_and_zero_denominators(db):
    opened = datetime.now(timezone.utc) - timedelta(hours=2)
    cases = [
        RecoveryCase(amount=10_000, currency="INR", status=RecoveryStatus.RECOVERED,
                     opened_at=opened, closed_at=opened + timedelta(hours=1),
                     batch_id="metrics", experiment_group=ExperimentGroup.TREATMENT.value),
        RecoveryCase(amount=30_000, currency="INR", status=RecoveryStatus.DIAGNOSED,
                     opened_at=opened, batch_id="metrics", experiment_group=ExperimentGroup.TREATMENT.value),
        RecoveryCase(amount=20_000, currency="INR", status=RecoveryStatus.RECOVERED,
                     opened_at=opened, closed_at=opened + timedelta(hours=2),
                     batch_id="metrics", experiment_group=ExperimentGroup.HOLDOUT.value),
        RecoveryCase(amount=20_000, currency="INR", status=RecoveryStatus.DIAGNOSED,
                     opened_at=opened, batch_id="metrics", experiment_group=ExperimentGroup.HOLDOUT.value),
    ]
    db.add_all(cases)
    db.commit()
    metrics = calculate_overview_metrics(db, "metrics")
    assert metrics["initial_money_at_risk"] == 80_000
    assert metrics["recovered_amount"] == 30_000
    assert metrics["outstanding_amount"] == 50_000
    assert metrics["treatment_recovery_rate"] == 0.25
    assert metrics["holdout_recovery_rate"] == 0.5
    assert metrics["incremental_lift"] == -0.25
    assert metrics["average_recovery_time_seconds"] == 5_400
    empty = calculate_overview_metrics(db, "missing")
    assert empty["gross_recovery_rate"] is None
    assert empty["treatment_recovery_rate"] is None
    assert empty["holdout_recovery_rate"] is None
    assert empty["incremental_lift"] is None


def test_batch_routes_filter_metrics_and_replay(client, monkeypatch):
    monkeypatch.setenv("DEMO_BATCH_ENABLED", "true")
    payload = {"seed": 9, "batch_size": 12, "treatment_percent": 75,
               "idempotency_key": "api-batch"}
    created = client.post("/demo/batches", json=payload)
    assert created.status_code == 200
    body = created.json()
    fetched = client.get(f"/demo/batches/{body['batch_id']}")
    metrics = client.get(f"/metrics/overview?batch_id={body['batch_id']}")
    replay = client.post("/demo/batches", json=payload)
    assert fetched.status_code == metrics.status_code == replay.status_code == 200
    assert metrics.json()["total_cases"] == 12
    assert replay.json()["idempotent_replay"] is True


def test_demo_batch_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("DEMO_BATCH_ENABLED", "false")
    response = client.post("/demo/batches", json={"batch_size": 1})
    assert response.status_code == 403
