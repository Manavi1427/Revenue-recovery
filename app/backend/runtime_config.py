from __future__ import annotations

import os
from urllib.parse import urlsplit


class RuntimeConfigurationError(ValueError):
    pass


def normalize_database_url(value: str) -> str:
    value = value.strip()
    return "postgresql://" + value[len("postgres://") :] if value.startswith("postgres://") else value


def frontend_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGINS") or os.getenv("FRONTEND_URL", "http://localhost:3000")
    origins = list(dict.fromkeys(part.strip().rstrip("/") for part in raw.split(",") if part.strip()))
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or origin == "*":
            raise RuntimeConfigurationError("Frontend origins must be explicit HTTP(S) origins")
    return origins


def validate_production_config() -> None:
    if os.getenv("APP_ENV", "development").strip().lower() != "production":
        return
    if not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeConfigurationError("DATABASE_URL is required in production")
    if not frontend_origins():
        raise RuntimeConfigurationError("At least one frontend origin is required in production")
    mode = os.getenv("RAZORPAY_MODE", "mock").strip().lower()
    if mode not in {"mock", "test"}:
        raise RuntimeConfigurationError("Only Razorpay mock or test mode is permitted")
    if mode == "test" and not (os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")):
        raise RuntimeConfigurationError("Razorpay Test Mode credentials are required")
    if os.getenv("RAZORPAY_WEBHOOKS_ENABLED", "true").strip().lower() == "true" and not os.getenv("RAZORPAY_WEBHOOK_SECRET"):
        raise RuntimeConfigurationError("Razorpay webhook secret is required")
