from __future__ import annotations

from datetime import datetime, timezone

from integrations.payment_link_provider import PaymentLinkRequest, PaymentLinkResult


class MockPaymentLinkProvider:
    """Offline provider with stable identifiers and no network calls."""

    def __init__(self, backend_public_url: str) -> None:
        self.backend_public_url = backend_public_url.rstrip("/")

    def create_payment_link(self, request: PaymentLinkRequest) -> PaymentLinkResult:
        reference_id = f"recoveriq_case_{request.case_id}_intervention_{request.intervention_id}"
        return PaymentLinkResult(
            provider="mock",
            mode="mock",
            payment_link_id=f"plink_mock_{request.intervention_id}",
            reference_id=reference_id,
            short_url=f"{self.backend_public_url}/demo/payment-links/{request.intervention_id}",
            status="created",
            created_at=datetime.now(timezone.utc),
        )
