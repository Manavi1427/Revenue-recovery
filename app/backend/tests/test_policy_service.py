import pytest

from database import RecoveryStatus
from services.policy_service import evaluate_policy
from services.recovery_actions import RecoveryAction


def policy(status=RecoveryStatus.DIAGNOSED, action=RecoveryAction.IMMEDIATE_RETRY, score=0.8, amount=10000, count=0, duplicate=False):
    return evaluate_policy(
        case_status=status, selected_action=action, recoverability_score=score,
        amount=amount, intervention_count=count, duplicate_pending=duplicate,
    )


@pytest.mark.parametrize("status", [RecoveryStatus.RECOVERED, RecoveryStatus.SUPPRESSED, RecoveryStatus.EXHAUSTED])
def test_terminal_cases_are_denied_and_preserved(status):
    result = policy(status=status)
    assert not result.allowed
    assert result.resulting_status == status


def test_invalid_inputs_and_review_policies():
    assert policy(score=None).resulting_status == RecoveryStatus.HUMAN_REVIEW
    assert policy(score=1.5).checks["score_is_valid"] is False
    assert policy(score=0.3).requires_human_review
    assert policy(amount=0).requires_human_review
    assert policy(action="NOT_ALLOWED").checks["action_is_approved"] is False
    assert policy(amount=1_000_000).requires_human_review
    assert policy(action=RecoveryAction.HUMAN_REVIEW).resulting_status == RecoveryStatus.HUMAN_REVIEW


def test_attempt_duplicate_and_allowed_outcomes_include_all_checks():
    exhausted = policy(count=3)
    assert exhausted.resulting_status == RecoveryStatus.EXHAUSTED
    duplicate = policy(count=1, duplicate=True)
    assert duplicate.resulting_status == RecoveryStatus.ACTION_SCHEDULED
    assert not duplicate.allowed
    allowed = policy()
    assert allowed.allowed
    assert allowed.resulting_status == RecoveryStatus.ACTION_SCHEDULED
    assert set(allowed.checks) == {
        "case_is_open", "case_not_recovered", "score_exists", "score_is_valid",
        "score_threshold_met", "amount_is_valid", "action_is_approved",
        "attempt_limit_ok", "no_duplicate_intervention", "high_value_review_not_required",
    }
