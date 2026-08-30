import pytest

from services.diagnosis_service import diagnose_payment_failure


@pytest.mark.parametrize(("data", "diagnosis", "action", "status"), [
    ({"error_reason": "INCORRECT_PIN"}, "Customer entered an incorrect PIN", "IMMEDIATE_RETRY", "DIAGNOSED"),
    ({"error_description": "Insufficient Funds"}, "Customer has insufficient balance", "RETRY_LATER", "DIAGNOSED"),
    ({"error_reason": "bank_unavailable"}, "Bank or provider is temporarily unavailable", "SUGGEST_ALTERNATIVE_METHOD", "DIAGNOSED"),
    ({"error_description": "Card Expired"}, "Payment instrument has expired", "REQUEST_NEW_METHOD", "DIAGNOSED"),
    ({}, "Failure reason could not be confidently diagnosed", "HUMAN_REVIEW", "HUMAN_REVIEW"),
])
def test_diagnosis_paths(data, diagnosis, action, status):
    result = diagnose_payment_failure(data)
    assert result == {"diagnosis": diagnosis, "recommended_action": action, "status": status}
