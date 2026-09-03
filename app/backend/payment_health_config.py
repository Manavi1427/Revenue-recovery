from dataclasses import dataclass
import os


class PaymentHealthConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PaymentHealthSettings:
    enabled: bool
    threshold: float
    minimum_attempts: int
    window_hours: int
    baselines: dict[str, float]


def _rate(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise PaymentHealthConfigurationError(f"{name} must be a decimal") from exc
    if not 0 <= value <= 1:
        raise PaymentHealthConfigurationError(f"{name} must be between 0 and 1")
    return value


def _positive_integer(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise PaymentHealthConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise PaymentHealthConfigurationError(f"{name} must be positive")
    return value


def get_payment_health_settings() -> PaymentHealthSettings:
    enabled_value = os.getenv("PAYMENT_HEALTH_ENABLED", "true").strip().lower()
    if enabled_value not in {"true", "false", "1", "0", "yes", "no"}:
        raise PaymentHealthConfigurationError("PAYMENT_HEALTH_ENABLED must be a boolean")
    return PaymentHealthSettings(
        enabled=enabled_value in {"true", "1", "yes"},
        threshold=_rate("PAYMENT_HEALTH_THRESHOLD", 0.10),
        minimum_attempts=_positive_integer("PAYMENT_HEALTH_MIN_ATTEMPTS", 10),
        window_hours=_positive_integer("PAYMENT_HEALTH_WINDOW_HOURS", 24),
        baselines={
            "upi": _rate("PAYMENT_HEALTH_BASELINE_UPI", 0.08),
            "card": _rate("PAYMENT_HEALTH_BASELINE_CARD", 0.06),
            "netbanking": _rate("PAYMENT_HEALTH_BASELINE_NETBANKING", 0.07),
            "wallet": _rate("PAYMENT_HEALTH_BASELINE_WALLET", 0.05),
        },
    )
