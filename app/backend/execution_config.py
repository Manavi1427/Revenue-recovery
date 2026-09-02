from __future__ import annotations

from dataclasses import dataclass
import os


class ExecutionConfigurationError(ValueError):
    """Raised when payment-link execution is configured unsafely."""


@dataclass(frozen=True)
class ExecutionSettings:
    razorpay_mode: str
    razorpay_key_id: str | None
    razorpay_key_secret: str | None
    message_mode: str
    backend_public_url: str

    @property
    def test_credentials_configured(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


def get_execution_settings(*, require_test_credentials: bool = False) -> ExecutionSettings:
    """Read and validate execution settings without exposing credential values."""

    mode = os.getenv("RAZORPAY_MODE", "mock").strip().lower()
    if mode not in {"mock", "test"}:
        raise ExecutionConfigurationError("RAZORPAY_MODE must be mock or test; live mode is not supported")
    key_id = os.getenv("RAZORPAY_KEY_ID") or None
    key_secret = os.getenv("RAZORPAY_KEY_SECRET") or None
    if mode == "test" and key_id and key_id.startswith("rzp_live_"):
        raise ExecutionConfigurationError("Live Razorpay keys cannot be used in test mode")
    if mode == "test" and require_test_credentials and not (key_id and key_secret):
        raise ExecutionConfigurationError("Razorpay Test Mode requires both credentials")
    message_mode = os.getenv("MESSAGE_MODE", "template").strip().lower()
    if message_mode != "template":
        raise ExecutionConfigurationError("Only template message mode is supported")
    public_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000").strip().rstrip("/")
    if not public_url:
        raise ExecutionConfigurationError("BACKEND_PUBLIC_URL must not be empty")
    return ExecutionSettings(mode, key_id, key_secret, message_mode, public_url)
