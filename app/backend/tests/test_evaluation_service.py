from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from database import AuditLog, Intervention, PaymentEvent, RecoveryCase, RecoveryStatus, utc_now
from services.evaluation_service import EvaluationCaseNotFound, evaluate_recovery_case


def make_case(db, *, score=0.8, amount=10000, status=RecoveryStatus.DIAGNOSED, reason="incorrect_pin"):
    case = RecoveryCase(
        payment_id=f"pay_{reason}_{amount}", amount=amount, status=status,
        diagnosis=reason.replace("_", " "), recommended_action="IMMEDIATE_RETRY",
        recoverability_score=score,
    )
    db.add(case)
    db.flush()
    event = PaymentEvent(
        event_id=f"evt_{case.id}", event_type="payment.failed", payment_id=case.payment_id,
        amount=amount, payment_method="card", error_reason=reason,
        normalized_payload={}, raw_payload={}, occurred_at=utc_now(), recovery_case_id=case.id,
    )
    db.add(event)
    db.commit()
    return case


def test_allowed_evaluation_is_audited_scheduled_and_idempotent(db):
    case = make_case(db)
    first = evaluate_recovery_case(db, case.id)
    second = evaluate_recovery_case(db, case.id)
    assert first.policy.allowed
    assert first.case_status == RecoveryStatus.ACTION_SCHEDULED
    assert second.intervention.id == first.intervention.id
    assert not second.policy.allowed
    assert db.scalar(select(func.count()).select_from(Intervention)) == 1
    actions = db.scalars(select(AuditLog.action).where(AuditLog.recovery_case_id == case.id)).all()
    assert actions.count("ACTION_SELECTED") == 1
    assert actions.count("POLICY_EVALUATED") == 1
    assert actions.count("INTERVENTION_SCHEDULED") == 1


def test_denied_high_value_creates_no_intervention_and_audits(db):
    case = make_case(db, amount=1_000_000)
    result = evaluate_recovery_case(db, case.id)
    assert not result.policy.allowed
    assert result.case_status == RecoveryStatus.HUMAN_REVIEW
    assert result.intervention is None
    assert db.scalar(select(func.count()).select_from(Intervention)) == 0
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.recovery_case_id == case.id)).all())
    assert {"ACTION_SELECTED", "POLICY_EVALUATED"}.issubset(actions)


def test_missing_score_uses_existing_scoring_service(db, monkeypatch):
    case = make_case(db, score=None)
    called = []

    def fake_score(_db, target):
        called.append(target.id)
        target.recoverability_score = 0.75
        return SimpleNamespace(source="RULES_FALLBACK")

    monkeypatch.setattr("services.evaluation_service.score_recovery_case", fake_score)
    result = evaluate_recovery_case(db, case.id)
    assert called == [case.id]
    assert result.score_source == "RULES_FALLBACK"


def test_saved_score_is_reused_and_unexpected_error_rolls_back(db, monkeypatch):
    case = make_case(db, score=0.8)
    monkeypatch.setattr("services.evaluation_service.score_recovery_case", lambda *_: pytest.fail("score should be reused"))
    monkeypatch.setattr("services.evaluation_service.evaluate_policy", lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        evaluate_recovery_case(db, case.id)
    db.refresh(case)
    assert case.status == RecoveryStatus.DIAGNOSED
    assert db.scalar(select(func.count()).select_from(Intervention)) == 0
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_missing_and_recovered_cases_do_not_schedule(db):
    with pytest.raises(EvaluationCaseNotFound):
        evaluate_recovery_case(db, "missing")
    case = make_case(db, score=None, status=RecoveryStatus.RECOVERED)
    result = evaluate_recovery_case(db, case.id)
    assert result.decision.selected_action.value == "STOP_CASE"
    assert result.case_status == RecoveryStatus.RECOVERED
    assert result.intervention is None
