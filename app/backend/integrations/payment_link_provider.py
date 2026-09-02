from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PaymentLinkRequest:
    case_id: str
    intervention_id: str
    amount: int
    currency: str


@dataclass(frozen=True)
class PaymentLinkResult:
    provider: str
    mode: str
    payment_link_id: str
    reference_id: str
    short_url: str
    status: str
    created_at: datetime


class PaymentLinkProviderError(RuntimeError):
    """A safe provider failure that contains no credentials or raw response."""


class PaymentLinkProvider(Protocol):
    def create_payment_link(self, request: PaymentLinkRequest) -> PaymentLinkResult:
        """Create one deterministic-reference payment link."""
