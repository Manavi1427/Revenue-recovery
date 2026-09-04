from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import razorpay

from integrations.payment_link_provider import (
    PaymentLinkProviderError, PaymentLinkRequest, PaymentLinkResult,
)


class RazorpayTestPaymentLinkProvider:
    """sanitized Payment Links using Razorpay Test Mode only."""

    def __init__(self, key_id: str, key_secret: str, client: Any | None = None) -> None:
        if key_id.startswith("rzp_live_"):
            raise PaymentLinkProviderError("Live Razorpay keys are not supported")
        self.client = client or razorpay.Client(auth=(key_id, key_secret))

    def create_payment_link(self, request: PaymentLinkRequest) -> PaymentLinkResult:
        if isinstance(request.amount, bool) or not isinstance(request.amount, int) or request.amount <= 0:
            raise PaymentLinkProviderError("Payment Link amount is invalid")
        if request.currency != "INR":
            raise PaymentLinkProviderError("Payment Link currency is unsupported")
        reference_id = f"recoveriq_case_{request.case_id}_intervention_{request.intervention_id}"
        payload = {
            "amount": request.amount,
            "currency": request.currency,
            "reference_id": reference_id,
            "description": f"RecoverIQ recovery for case {request.case_id}",
            "accept_partial": False,
            "reminder_enable": False,
            "notify": {"sms": False, "email": False},
        }
        try:
            response = self.client.payment_link.create(payload)
            payment_link_id = response["id"]
            short_url = response["short_url"]
            status = response.get("status", "created")
            created_value = response.get("created_at")
            created_at = (
                datetime.fromtimestamp(created_value, tz=timezone.utc)
                if isinstance(created_value, (int, float))
                else datetime.now(timezone.utc)
            )
            if not all(isinstance(value, str) and value for value in (payment_link_id, short_url, status)):
                raise ValueError("Provider response fields are invalid")
        except Exception as exc:
            raise PaymentLinkProviderError("Razorpay Test Mode could not create the payment link") from exc
        return PaymentLinkResult(
            provider="razorpay", mode="test", payment_link_id=payment_link_id,
            reference_id=reference_id, short_url=short_url, status=status,
            created_at=created_at,
        )
