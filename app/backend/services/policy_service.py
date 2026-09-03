from __future__ import annotations

from dataclasses import dataclass

from database import RecoveryStatus
from services.recovery_actions import (
    HIGH_VALUE_REVIEW_THRESHOLD,
    MAX_INTERVENTIONS_PER_CASE,
    MIN_AUTOMATIC_SCORE,
    POLICY_VERSION,
    RecoveryAction,
)


@dataclass(frozen=True)
class PolicyResult:
    """Every deterministic safety check and its resulting case state."""

    allowed: bool
    checks: dict[str, bool]
    denial_reason: str | None
    resulting_status: RecoveryStatus
    requires_human_review: bool
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class PaymentHealthPolicyResult:
    original_action: RecoveryAction
    final_action: RecoveryAction
    affected: bool
    reason: str


def apply_payment_health_policy(
    action: RecoveryAction, method_status: str | None
) -> PaymentHealthPolicyResult:
    """Replace only unsuitable same-method retry actions when degraded."""

    if method_status != "DEGRADED":
        return PaymentHealthPolicyResult(
            action, action, False,
            "Payment Health suppression was not required.",
        )
    if action not in {RecoveryAction.IMMEDIATE_RETRY, RecoveryAction.RETRY_LATER}:
        return PaymentHealthPolicyResult(
            action, action, False,
            "The selected action does not depend on retrying the degraded method.",
        )
    return PaymentHealthPolicyResult(
        action, RecoveryAction.SUGGEST_ALTERNATIVE_METHOD, True,
        "Same-method retry suppressed because the payment method is degraded.",
    )


def evaluate_policy(
    *,
    case_status: RecoveryStatus,
    selected_action: RecoveryAction | str,
    recoverability_score: float | None,
    amount: int,
    intervention_count: int,
    duplicate_pending: bool,
    experiment_group: str | None = None,
) -> PolicyResult:
    """Apply financial-safety policy without calling ML or the database."""

    try:
        action = RecoveryAction(selected_action)
        approved = True
    except (TypeError, ValueError):
        action, approved = None, False
    score_exists = recoverability_score is not None
    score_valid = score_exists and 0.0 <= float(recoverability_score) <= 1.0
    checks = {
        "case_is_open": case_status not in {RecoveryStatus.RECOVERED, RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED},
        "case_not_recovered": case_status != RecoveryStatus.RECOVERED,
        "score_exists": score_exists,
        "score_is_valid": score_valid,
        "score_threshold_met": score_valid and float(recoverability_score) >= MIN_AUTOMATIC_SCORE,
        "amount_is_valid": int(amount) > 0,
        "action_is_approved": approved,
        "attempt_limit_ok": int(intervention_count) < MAX_INTERVENTIONS_PER_CASE,
        "no_duplicate_intervention": not duplicate_pending,
        "high_value_review_not_required": int(amount) < HIGH_VALUE_REVIEW_THRESHOLD,
    }
    if experiment_group is not None:
        checks["case_is_not_holdout"] = experiment_group != "HOLDOUT"

    if case_status == RecoveryStatus.RECOVERED:
        return PolicyResult(False, checks, "Case is already recovered", RecoveryStatus.RECOVERED, False)
    if case_status in {RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED}:
        return PolicyResult(False, checks, "Case is terminal or suppressed", case_status, False)
    if experiment_group == "HOLDOUT":
        return PolicyResult(
            False, checks, "Holdout cases cannot receive recovery interventions",
            case_status, False,
        )
    if not approved:
        return PolicyResult(False, checks, "Action is not in the approved allowlist", RecoveryStatus.HUMAN_REVIEW, True)
    if action == RecoveryAction.STOP_CASE:
        return PolicyResult(False, checks, "Stop actions never create interventions", case_status, False)
    if case_status == RecoveryStatus.HUMAN_REVIEW or action == RecoveryAction.HUMAN_REVIEW:
        return PolicyResult(False, checks, "Case requires human review", RecoveryStatus.HUMAN_REVIEW, True)
    if not score_exists or not score_valid:
        return PolicyResult(False, checks, "Recoverability score is missing or invalid", RecoveryStatus.HUMAN_REVIEW, True)
    if not checks["score_threshold_met"]:
        return PolicyResult(False, checks, "Score is below the automatic-action threshold", RecoveryStatus.HUMAN_REVIEW, True)
    if not checks["amount_is_valid"]:
        return PolicyResult(False, checks, "Amount must be positive", RecoveryStatus.HUMAN_REVIEW, True)
    if duplicate_pending:
        return PolicyResult(False, checks, "Equivalent intervention is already pending", RecoveryStatus.ACTION_SCHEDULED, False)
    if not checks["attempt_limit_ok"]:
        return PolicyResult(False, checks, "Maximum intervention attempts reached", RecoveryStatus.EXHAUSTED, False)
    if not checks["high_value_review_not_required"]:
        return PolicyResult(False, checks, "High-value case requires human review", RecoveryStatus.HUMAN_REVIEW, True)
    return PolicyResult(True, checks, None, RecoveryStatus.ACTION_SCHEDULED, False)
