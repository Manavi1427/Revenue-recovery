from database import RecoveryStatus
from services.decision_service import select_recovery_action
from services.recovery_actions import RecoveryAction


def decide(status=RecoveryStatus.DIAGNOSED, diagnosis="incorrect_pin", action="IMMEDIATE_RETRY", score=0.8, attempts=1, interventions=0):
    return select_recovery_action(
        case_status=status, diagnosis=diagnosis, diagnosed_action=action,
        recoverability_score=score, amount=10001, payment_method="card",
        previous_attempts=attempts, intervention_count=interventions,
    )


def test_stopping_and_review_precedence():
    assert decide(status=RecoveryStatus.RECOVERED).selected_action == RecoveryAction.STOP_CASE
    assert decide(status=RecoveryStatus.SUPPRESSED).selected_action == RecoveryAction.STOP_CASE
    assert decide(status=RecoveryStatus.HUMAN_REVIEW).selected_action == RecoveryAction.HUMAN_REVIEW
    assert decide(score=0.2).selected_action == RecoveryAction.HUMAN_REVIEW


def test_failure_specific_bounded_actions():
    assert decide(score=0.8).selected_action == RecoveryAction.IMMEDIATE_RETRY
    assert decide(score=0.6).selected_action == RecoveryAction.CREATE_PAYMENT_LINK
    assert decide(diagnosis="insufficient_funds", action="RETRY_LATER", score=0.4).selected_action == RecoveryAction.RETRY_LATER
    assert decide(diagnosis="bank unavailable", action="SUGGEST_ALTERNATIVE_METHOD").selected_action == RecoveryAction.SUGGEST_ALTERNATIVE_METHOD
    assert decide(diagnosis="expired card", action="REQUEST_NEW_METHOD").selected_action == RecoveryAction.REQUEST_NEW_METHOD


def test_integer_expected_value_penalties_and_determinism():
    first = decide(score=0.5, attempts=3, interventions=2)
    second = decide(score=0.5, attempts=3, interventions=2)
    assert first == second
    assert isinstance(first.expected_recovery_value, int)
    assert first.expected_recovery_value == 5000
    assert first.utility == first.expected_recovery_value - first.operational_cost - 200 - 200
    assert all(isinstance(action, RecoveryAction) for action in first.candidate_actions)
