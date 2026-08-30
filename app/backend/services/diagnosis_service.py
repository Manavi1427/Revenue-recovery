from typing import Any


def diagnose_payment_failure(payment_data: dict[str, Any]) -> dict[str, str]:
    """Map Razorpay failure details to a deterministic recovery decision."""

    searchable = " ".join(
        str(payment_data.get(field) or "")
        for field in (
            "error_code",
            "error_source",
            "error_step",
            "error_reason",
            "error_description",
            "method",
        )
    ).lower()

    if "incorrect_pin" in searchable or "incorrect pin" in searchable:
        return {
            "diagnosis": "Customer entered an incorrect PIN",
            "recommended_action": "IMMEDIATE_RETRY",
            "status": "DIAGNOSED",
        }
    if "insufficient_funds" in searchable or "insufficient funds" in searchable:
        return {
            "diagnosis": "Customer has insufficient balance",
            "recommended_action": "RETRY_LATER",
            "status": "DIAGNOSED",
        }
    if any(term in searchable for term in ("bank unavailable", "provider unavailable", "temporarily unavailable", "bank_unavailable")):
        return {
            "diagnosis": "Bank or provider is temporarily unavailable",
            "recommended_action": "SUGGEST_ALTERNATIVE_METHOD",
            "status": "DIAGNOSED",
        }
    if "expired_card" in searchable or "expired card" in searchable or "card expired" in searchable:
        return {
            "diagnosis": "Payment instrument has expired",
            "recommended_action": "REQUEST_NEW_METHOD",
            "status": "DIAGNOSED",
        }
    return {
        "diagnosis": "Failure reason could not be confidently diagnosed",
        "recommended_action": "HUMAN_REVIEW",
        "status": "HUMAN_REVIEW",
    }
