from __future__ import annotations

from dataclasses import dataclass

from database import RecoveryStatus
from services.recovery_actions import (
    DECISION_VERSION,
    FATIGUE_PENALTY_PER_INTERVENTION,
    OPERATIONAL_COSTS,
    RISK_PENALTY_PER_REPEAT_ATTEMPT,
    RecoveryAction,
)


@dataclass(frozen=True)
class DecisionResult:
    """A bounded action and its transparent expected-value calculation."""

    selected_action: RecoveryAction
    recoverability_score: float
    expected_recovery_value: int
    operational_cost: int
    fatigue_penalty: int
    risk_penalty: int
    utility: int
    explanation: list[str]
    candidate_actions: list[RecoveryAction]
    decision_version: str = DECISION_VERSION


def _text(*values: str | None) -> str:
    return " ".join(str(value or "").lower().replace("_", " ") for value in values)


def select_recovery_action(
    *,
    case_status: RecoveryStatus,
    diagnosis: str | None,
    diagnosed_action: str | None,
    recoverability_score: float,
    amount: int,
    payment_method: str | None,
    previous_attempts: int,
    intervention_count: int,
) -> DecisionResult:
    """Select exactly one action from the fixed allowlist using ordered rules."""

    score = max(0.0, min(float(recoverability_score), 1.0))
    evidence = _text(diagnosis, diagnosed_action, payment_method)
    explanation: list[str] = []

    if case_status == RecoveryStatus.RECOVERED:
        action, candidates = RecoveryAction.STOP_CASE, [RecoveryAction.STOP_CASE]
        explanation.append("Recovered cases must not receive another recovery action")
    elif case_status in {RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED}:
        action, candidates = RecoveryAction.STOP_CASE, [RecoveryAction.STOP_CASE]
        explanation.append("Terminal or suppressed cases must remain stopped")
    elif case_status == RecoveryStatus.HUMAN_REVIEW or "human review" in evidence:
        action, candidates = RecoveryAction.HUMAN_REVIEW, [RecoveryAction.HUMAN_REVIEW]
        explanation.append("The diagnosis requires human review")
    elif score < 0.25:
        action, candidates = RecoveryAction.HUMAN_REVIEW, [RecoveryAction.HUMAN_REVIEW]
        explanation.append("Recoverability is too uncertain for automatic action")
    elif "incorrect pin" in evidence or "authentication" in evidence:
        candidates = [RecoveryAction.IMMEDIATE_RETRY, RecoveryAction.CREATE_PAYMENT_LINK, RecoveryAction.HUMAN_REVIEW]
        if score >= 0.65:
            action = RecoveryAction.IMMEDIATE_RETRY
            explanation.extend(["Incorrect PIN is customer-correctable", "Score met the immediate-retry threshold"])
        else:
            action = RecoveryAction.CREATE_PAYMENT_LINK
            explanation.extend(["Incorrect PIN is customer-correctable", "Score was below the immediate-retry threshold"])
    elif "insufficient" in evidence:
        candidates = [RecoveryAction.RETRY_LATER, RecoveryAction.HUMAN_REVIEW]
        action = RecoveryAction.RETRY_LATER if score >= 0.35 else RecoveryAction.HUMAN_REVIEW
        explanation.append("Insufficient funds may improve later or require review")
    elif "bank" in evidence and ("unavailable" in evidence or "provider" in evidence):
        action = RecoveryAction.SUGGEST_ALTERNATIVE_METHOD
        candidates = [RecoveryAction.SUGGEST_ALTERNATIVE_METHOD, RecoveryAction.CREATE_PAYMENT_LINK, RecoveryAction.HUMAN_REVIEW]
        explanation.append("The bank or provider is temporarily unavailable")
    elif "expired" in evidence or "invalid instrument" in evidence or "request new method" in evidence:
        action = RecoveryAction.REQUEST_NEW_METHOD
        candidates = [RecoveryAction.REQUEST_NEW_METHOD, RecoveryAction.HUMAN_REVIEW]
        explanation.append("The current payment instrument cannot be reused")
    elif score >= 0.40:
        action = RecoveryAction.CREATE_PAYMENT_LINK
        candidates = [RecoveryAction.CREATE_PAYMENT_LINK, RecoveryAction.HUMAN_REVIEW]
        explanation.append("A recognized case met the bounded fallback threshold")
    else:
        action, candidates = RecoveryAction.HUMAN_REVIEW, [RecoveryAction.HUMAN_REVIEW]
        explanation.append("No bounded automatic action met its threshold")

    expected_value = round(score * max(0, int(amount)))
    operational_cost = OPERATIONAL_COSTS[action]
    fatigue_penalty = max(0, int(intervention_count)) * FATIGUE_PENALTY_PER_INTERVENTION
    risk_penalty = max(int(previous_attempts) - 1, 0) * RISK_PENALTY_PER_REPEAT_ATTEMPT
    utility = expected_value - operational_cost - fatigue_penalty - risk_penalty
    explanation.append(
        f"Utility subtracts {operational_cost} paise cost, {fatigue_penalty} paise fatigue, and {risk_penalty} paise repeat risk"
    )
    return DecisionResult(
        action, score, expected_value, operational_cost, fatigue_penalty,
        risk_penalty, utility, explanation, candidates,
    )
