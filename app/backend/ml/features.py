from __future__ import annotations

from datetime import datetime
from typing import Any


NUMERIC_FEATURES = ["amount", "hour_of_day", "day_of_week", "previous_attempts"]
CATEGORICAL_FEATURES = ["payment_method", "error_source", "error_step", "error_reason"]
MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COLUMN = "recovered_within_24h"


def build_feature_row(case: Any, event: Any | None, previous_attempts: int) -> dict[str, Any]:
    """Build the one inference row shared with the training contract."""

    occurred_at = getattr(event, "occurred_at", None)
    if not isinstance(occurred_at, datetime):
        occurred_at = getattr(case, "opened_at", None)
    hour = occurred_at.hour if isinstance(occurred_at, datetime) else 0
    weekday = occurred_at.weekday() if isinstance(occurred_at, datetime) else 0

    def category(name: str) -> str:
        value = getattr(event, name, None) if event is not None else None
        return str(value).lower() if value else "unknown"

    return {
        "amount": max(0, int(getattr(case, "amount", 0) or 0)),
        "hour_of_day": hour,
        "day_of_week": weekday,
        "previous_attempts": max(0, int(previous_attempts or 0)),
        "payment_method": category("payment_method"),
        "error_source": category("error_source"),
        "error_step": category("error_step"),
        "error_reason": category("error_reason"),
    }
