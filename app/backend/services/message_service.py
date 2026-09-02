from __future__ import annotations

from dataclasses import dataclass

from services.recovery_actions import RecoveryAction


@dataclass(frozen=True)
class RecoveryMessage:
    """A deterministic message preview; Part 3 never sends it."""

    title: str
    body: str
    cta_label: str
    payment_url: str
    language: str = "en"
    source: str = "TEMPLATE"


def format_amount(amount: int, currency: str) -> str:
    """Format integer minor units for display without changing stored money."""

    major, minor = divmod(int(amount), 100)
    prefix = "₹" if currency.upper() == "INR" else f"{currency.upper()} "
    return f"{prefix}{major}.{minor:02d}"


def generate_recovery_message(
    *, action: RecoveryAction, amount: int, currency: str,
    payment_url: str, case_id: str,
) -> RecoveryMessage:
    """Generate an action-specific preview using verified facts only."""

    del case_id  # Kept as a verified extension point; not exposed to customers yet.
    display_amount = format_amount(amount, currency)
    messages = {
        RecoveryAction.IMMEDIATE_RETRY: (
            "Retry your payment",
            f"Your payment of {display_amount} was not completed. You can retry using the link below.",
            "Retry payment",
        ),
        RecoveryAction.RETRY_LATER: (
            "Complete your payment when convenient",
            f"Your payment of {display_amount} was not completed. You can retry when convenient using the link below.",
            "Complete payment",
        ),
        RecoveryAction.CREATE_PAYMENT_LINK: (
            "Complete your payment",
            f"Your payment of {display_amount} was not completed. Use the link below if you wish to complete it.",
            "Complete payment",
        ),
        RecoveryAction.SUGGEST_ALTERNATIVE_METHOD: (
            "Choose another payment method",
            f"Your payment of {display_amount} was not completed. You can use the link below and choose another available method.",
            "Choose payment method",
        ),
        RecoveryAction.REQUEST_NEW_METHOD: (
            "Use a different payment method",
            f"Your payment of {display_amount} was not completed. Please use a different payment method through the link below.",
            "Use another method",
        ),
    }
    if action not in messages:
        raise ValueError(f"Action {action.value} cannot produce a recovery message")
    title, body, cta = messages[action]
    return RecoveryMessage(title, body, cta, payment_url)
