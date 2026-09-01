from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import AuditLog, PaymentEvent, RecoveryCase
from ml.features import build_feature_row
from ml.predictor import ModelUnavailableError, predict_probability


@dataclass(frozen=True)
class RuleScoreResult:
    """A transparent score and the reasons that produced it."""

    score: float
    explanation: list[str]


@dataclass(frozen=True)
class ScoringResult:
    """The selected score plus its rule and optional ML evidence."""

    final_score: float
    source: str
    rule_score: float
    ml_score: float | None
    explanation: list[str]
    model_version: str | None


def _normalized(*values: str | None) -> str:
    """Join optional fields into safe, case-insensitive searchable text."""

    return " ".join(str(value or "").lower().replace("_", " ") for value in values)


def calculate_rule_score(
    *,
    amount: int,
    payment_method: str | None,
    error_source: str | None,
    error_step: str | None,
    error_reason: str | None,
    previous_attempts: int,
) -> RuleScoreResult:
    """Calculate the reliable, deterministic recoverability rule score."""

    del amount  # Reserved for future evidence-based rules.
    score = 0.50
    reasons = ["Started from baseline recovery probability"]
    failure = _normalized(error_source, error_step, error_reason)
    method = _normalized(payment_method)

    if "incorrect pin" in failure:
        score += 0.30
        reasons.append("Incorrect PIN is usually customer-correctable")
    if "bank unavailable" in failure or "provider unavailable" in failure:
        score += 0.10
        reasons.append("Temporary provider availability may improve on retry")
    if "upi" in method:
        score += 0.05
        reasons.append("UPI payment indicates active checkout intent")
    if "customer" in _normalized(error_source):
        score += 0.05
        reasons.append("Customer-originated failure may be correctable")
    if "insufficient funds" in failure:
        score -= 0.10
        reasons.append("Insufficient funds may require waiting or another method")
    if "expired card" in failure or "card expired" in failure:
        score -= 0.20
        reasons.append("An expired card requires another payment method")
    if not failure.strip() or "unknown" in failure or "unclassified" in failure:
        score -= 0.20
        reasons.append("Unknown failure reduces confidence in recovery")

    extra_failures = max(0, int(previous_attempts or 0) - 1)
    if extra_failures:
        score -= 0.05 * extra_failures
        reasons.append("Repeated failed attempts reduce recovery confidence")

    return RuleScoreResult(score=round(max(0.0, min(score, 1.0)), 6), explanation=reasons)


def score_recovery_case(db: Session, case: RecoveryCase) -> ScoringResult:
    """Score, persist, and audit a case without changing its lifecycle status."""

    events = db.scalars(
        select(PaymentEvent).where(PaymentEvent.recovery_case_id == case.id).order_by(PaymentEvent.occurred_at.desc())
    ).all()
    failed_events = [event for event in events if event.event_type == "payment.failed"]
    event = failed_events[0] if failed_events else (events[0] if events else None)
    attempts = len(failed_events)
    rule = calculate_rule_score(
        amount=case.amount,
        payment_method=getattr(event, "payment_method", None),
        error_source=getattr(event, "error_source", None),
        error_step=getattr(event, "error_step", None),
        error_reason=getattr(event, "error_reason", None),
        previous_attempts=attempts,
    )
    explanation = list(rule.explanation)
    ml_score: float | None = None
    model_version: str | None = None
    try:
        ml_score, model_version = predict_probability(build_feature_row(case, event, attempts))
        final_score, source = ml_score, "ML"
        explanation.append("ML prototype prediction completed successfully")
    except ModelUnavailableError:
        final_score, source = rule.score, "RULES_FALLBACK"
        explanation.append("Rule score used because the optional ML prototype was unavailable")

    result = ScoringResult(round(final_score, 6), source, rule.score, None if ml_score is None else round(ml_score, 6), explanation, model_version)
    decision_data = {
        "final_score": result.final_score, "source": result.source,
        "rule_score": result.rule_score, "ml_score": result.ml_score,
        "model_version": result.model_version, "explanation": result.explanation,
        "dataset_type": "synthetic",
    }
    case.recoverability_score = result.final_score
    latest = db.scalar(select(AuditLog).where(
        AuditLog.recovery_case_id == case.id, AuditLog.action == "RECOVERY_SCORED"
    ).order_by(AuditLog.created_at.desc()))
    # Avoid audit noise only when the complete scoring decision is unchanged.
    if latest is None or latest.decision_data != decision_data:
        db.add(AuditLog(
            recovery_case_id=case.id,
            payment_event_id=event.id if event else None,
            action="RECOVERY_SCORED", actor="SYSTEM",
            previous_status=case.status, new_status=case.status,
            decision_data=decision_data,
        ))
    db.commit()
    db.refresh(case)
    return result
