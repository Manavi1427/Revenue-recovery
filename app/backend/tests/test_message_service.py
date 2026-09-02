import pytest

from services.message_service import format_amount, generate_recovery_message
from services.recovery_actions import RecoveryAction


def test_amount_is_formatted_from_paise():
    assert format_amount(12500, "INR") == "₹125.00"
    assert format_amount(12501, "INR") == "₹125.01"


@pytest.mark.parametrize("action", [
    RecoveryAction.IMMEDIATE_RETRY,
    RecoveryAction.RETRY_LATER,
    RecoveryAction.CREATE_PAYMENT_LINK,
    RecoveryAction.SUGGEST_ALTERNATIVE_METHOD,
    RecoveryAction.REQUEST_NEW_METHOD,
])
def test_templates_vary_by_action_and_use_verified_facts(action):
    result = generate_recovery_message(
        action=action, amount=12500, currency="INR",
        payment_url="http://localhost/mock", case_id="case-1",
    )
    assert "₹125.00" in result.body
    assert result.payment_url == "http://localhost/mock"
    assert result.source == "TEMPLATE"
    assert result.language == "en"
    forbidden = ("discount", "expires", "deadline", "refund", "debited", "risk score")
    assert not any(term in result.body.lower() for term in forbidden)


def test_non_executable_actions_cannot_generate_messages():
    for action in (RecoveryAction.HUMAN_REVIEW, RecoveryAction.STOP_CASE):
        with pytest.raises(ValueError):
            generate_recovery_message(
                action=action, amount=100, currency="INR",
                payment_url="http://localhost/mock", case_id="case-1",
            )
