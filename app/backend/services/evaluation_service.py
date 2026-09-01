from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import AuditLog, Intervention, PaymentEvent, RecoveryCase, RecoveryStatus
from services.decision_service import DecisionResult, select_recovery_action
from services.policy_service import PolicyResult, evaluate_policy
from services.scoring_service import score_recovery_case


logger = logging.getLogger(__name__)


class EvaluationCaseNotFound(LookupError):
    """Raised when an evaluation targets an unknown recovery case."""


@dataclass(frozen=True)
class EvaluationResult:
    """Complete decision, policy, and optional pending intervention result."""

    case_id: str
    case_status: object
    recoverability_score: float
    score_source: str
    decision: DecisionResult
    policy: PolicyResult
    intervention: Intervention | None


def _decision_data(decision: DecisionResult) -> dict[str, object]:
    data = asdict(decision)
    data["selected_action"] = decision.selected_action.value
    data["candidate_actions"] = [action.value for action in decision.candidate_actions]
    return data


def _policy_data(policy: PolicyResult) -> dict[str, object]:
    return {
        "allowed": policy.allowed,
        "denial_reason": policy.denial_reason,
        "resulting_status": policy.resulting_status.value,
        "requires_human_review": policy.requires_human_review,
        "policy_version": policy.policy_version,
    }


def _add_audit_unless_identical(db: Session, audit: AuditLog) -> None:
    latest = db.scalar(select(AuditLog).where(
        AuditLog.recovery_case_id == audit.recovery_case_id,
        AuditLog.action == audit.action,
    ).order_by(AuditLog.created_at.desc()))
    if latest is None or latest.decision_data != audit.decision_data or latest.policy_checks != audit.policy_checks:
        db.add(audit)


def _latest_score_source(db: Session, case_id: str) -> str:
    log = db.scalar(select(AuditLog).where(
        AuditLog.recovery_case_id == case_id,
        AuditLog.action == "RECOVERY_SCORED",
    ).order_by(AuditLog.created_at.desc()))
    return str(log.decision_data.get("source", "SAVED")) if log else "SAVED"


def evaluate_recovery_case(db: Session, case_id: str) -> EvaluationResult:
    """Score if needed, decide, enforce policy, and schedule atomically."""

    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == case_id).with_for_update())
    if case is None:
        raise EvaluationCaseNotFound(case_id)

    try:
        score_source = _latest_score_source(db, case.id)
        if case.recoverability_score is None and case.status in {
            RecoveryStatus.RECOVERED, RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED,
        }:
            score, score_source = 0.0, "NOT_REQUIRED"
        elif case.recoverability_score is None:
            scoring = score_recovery_case(db, case)
            score_source = scoring.source
            score = float(case.recoverability_score)
        else:
            score = float(case.recoverability_score)

        failed_events = db.scalars(select(PaymentEvent).where(
            PaymentEvent.recovery_case_id == case.id,
            PaymentEvent.event_type == "payment.failed",
        ).order_by(PaymentEvent.occurred_at.desc())).all()
        latest_event = failed_events[0] if failed_events else None
        counted_interventions = db.scalars(select(Intervention).where(
            Intervention.recovery_case_id == case.id,
            Intervention.cancelled_at.is_(None),
        )).all()
        decision = select_recovery_action(
            case_status=case.status,
            diagnosis=" ".join(filter(None, [case.diagnosis, getattr(latest_event, "error_reason", None), getattr(latest_event, "error_step", None)])),
            diagnosed_action=case.recommended_action,
            recoverability_score=score,
            amount=case.amount,
            payment_method=getattr(latest_event, "payment_method", None),
            previous_attempts=len(failed_events),
            intervention_count=len(counted_interventions),
        )
        existing = next((item for item in counted_interventions if
            item.action_type == decision.selected_action.value
            and item.executed_at is None and item.cancelled_at is None
        ), None)
        if existing is not None:
            # Return the original pending work without creating more attempts or audit noise.
            decision = select_recovery_action(
                case_status=case.status, diagnosis=case.diagnosis,
                diagnosed_action=case.recommended_action, recoverability_score=score,
                amount=case.amount, payment_method=getattr(latest_event, "payment_method", None),
                previous_attempts=len(failed_events),
                intervention_count=max(0, len(counted_interventions) - 1),
            )
            policy = evaluate_policy(
                case_status=case.status, selected_action=decision.selected_action,
                recoverability_score=score, amount=case.amount,
                intervention_count=len(counted_interventions), duplicate_pending=True,
            )
            return EvaluationResult(case.id, case.status, score, score_source, decision, policy, existing)

        previous_status = case.status
        decision_json = _decision_data(decision)
        _add_audit_unless_identical(db, AuditLog(
            recovery_case_id=case.id,
            payment_event_id=latest_event.id if latest_event else None,
            action="ACTION_SELECTED", actor="SYSTEM",
            previous_status=previous_status, new_status=previous_status,
            decision_data=decision_json,
        ))
        policy = evaluate_policy(
            case_status=case.status, selected_action=decision.selected_action,
            recoverability_score=score, amount=case.amount,
            intervention_count=len(counted_interventions), duplicate_pending=False,
        )
        case.status = policy.resulting_status
        _add_audit_unless_identical(db, AuditLog(
            recovery_case_id=case.id,
            payment_event_id=latest_event.id if latest_event else None,
            action="POLICY_EVALUATED", actor="SYSTEM",
            previous_status=previous_status, new_status=case.status,
            decision_data=_policy_data(policy), policy_checks=policy.checks,
        ))

        intervention = None
        if policy.allowed:
            intervention = Intervention(
                recovery_case_id=case.id,
                action_type=decision.selected_action.value,
                channel="PENDING",
                scheduled_at=datetime.now(timezone.utc),
                cost=decision.operational_cost,
                action_payload={
                    "recoverability_score": score,
                    "expected_recovery_value": decision.expected_recovery_value,
                    "decision_version": decision.decision_version,
                    "policy_version": policy.policy_version,
                    "status": "PENDING_EXECUTION",
                },
            )
            db.add(intervention)
            db.flush()
            db.add(AuditLog(
                recovery_case_id=case.id,
                payment_event_id=latest_event.id if latest_event else None,
                action="INTERVENTION_SCHEDULED", actor="SYSTEM",
                previous_status=previous_status, new_status=case.status,
                decision_data={"intervention_id": intervention.id, "selected_action": decision.selected_action.value},
            ))
        db.commit()
        db.refresh(case)
        if intervention is not None:
            db.refresh(intervention)
        return EvaluationResult(case.id, case.status, score, score_source, decision, policy, intervention)
    except Exception:
        db.rollback()
        logger.exception("Recovery case evaluation failed", extra={"case_id": case_id})
        raise
