from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import PaymentEvent, RecoveryCase
from payment_health_config import PaymentHealthSettings, get_payment_health_settings


KNOWN_METHODS = ("upi", "card", "netbanking", "wallet")


class PaymentHealthDisabled(RuntimeError):
    pass


class PaymentHealthBatchNotFound(LookupError):
    pass


def get_payment_method_counts(
    db: Session, *, batch_id: str | None, window_start: datetime | None
) -> dict[str, tuple[int, int]]:
    statement = select(PaymentEvent)
    if batch_id is not None:
        statement = statement.where(PaymentEvent.batch_id == batch_id)
    elif window_start is not None:
        statement = statement.where(PaymentEvent.occurred_at >= window_start)
    events = db.scalars(statement).all()

    # One non-null payment_id is one logical payment attempt. A payment that
    # failed and was later captured remains one failed initial attempt; the
    # recovery capture neither enlarges the denominator nor erases the failure.
    attempts: dict[str, dict[str, object]] = {}
    for event in events:
        key = event.payment_id or f"event:{event.event_id}"
        entry = attempts.setdefault(key, {"method": None, "failed": False})
        if event.payment_method:
            entry["method"] = event.payment_method.strip().lower()
        if event.event_type == "payment.failed":
            entry["failed"] = True
    counts: dict[str, list[int]] = {}
    for entry in attempts.values():
        method = entry["method"]
        if not isinstance(method, str) or not method:
            continue
        values = counts.setdefault(method, [0, 0])
        values[0] += 1
        values[1] += int(entry["failed"] is True)
    return {method: (values[0], values[1]) for method, values in counts.items()}


def evaluate_method_health(
    payment_method: str,
    total_attempts: int,
    failed_attempts: int,
    settings: PaymentHealthSettings,
) -> dict[str, object]:
    baseline = settings.baselines.get(payment_method)
    observed = round(failed_attempts / total_attempts, 6) if total_attempts else None
    if baseline is None:
        status, limit = "NO_BASELINE", None
        reason = "No failure-rate baseline is configured for this payment method."
    elif total_attempts < settings.minimum_attempts:
        status, limit = "INSUFFICIENT_DATA", round(baseline + settings.threshold, 6)
        reason = f"At least {settings.minimum_attempts} distinct attempts are required."
    else:
        limit = round(baseline + settings.threshold, 6)
        status = "DEGRADED" if observed is not None and observed > limit else "HEALTHY"
        reason = (
            "Observed failure rate exceeded the configured degradation limit."
            if status == "DEGRADED"
            else "Observed failure rate is within the configured degradation limit."
        )
    degraded = status == "DEGRADED"
    return {
        "payment_method": payment_method,
        "status": status,
        "total_attempts": total_attempts,
        "failed_attempts": failed_attempts,
        "observed_failure_rate": observed,
        "baseline_failure_rate": baseline,
        "threshold": settings.threshold,
        "degradation_limit": limit,
        "recommended_action": "SUGGEST_ALTERNATIVE_METHOD" if degraded else None,
        "reminders_suppressed": degraded,
        "reason": reason,
    }


def get_payment_health(
    db: Session, batch_id: str | None = None
) -> dict[str, object]:
    settings = get_payment_health_settings()
    if not settings.enabled:
        raise PaymentHealthDisabled("Payment Health is disabled")
    if batch_id is not None and db.scalar(select(RecoveryCase.id).where(
        RecoveryCase.batch_id == batch_id
    )) is None:
        raise PaymentHealthBatchNotFound("Demo batch not found")
    generated_at = datetime.now(timezone.utc)
    window_start = None if batch_id is not None else generated_at - timedelta(
        hours=settings.window_hours
    )
    counts = get_payment_method_counts(
        db, batch_id=batch_id, window_start=window_start
    )
    methods = []
    for method in (*KNOWN_METHODS, *sorted(set(counts) - set(KNOWN_METHODS))):
        total, failed = counts.get(method, (0, 0))
        methods.append(evaluate_method_health(method, total, failed, settings))
    degraded = [str(item["payment_method"]) for item in methods if item["status"] == "DEGRADED"]
    if degraded:
        overall = "DEGRADED"
    elif any(item["status"] == "HEALTHY" for item in methods):
        overall = "HEALTHY"
    else:
        overall = "INSUFFICIENT_DATA"
    return {
        "batch_id": batch_id,
        "window_start": window_start,
        "window_end": generated_at if batch_id is None else None,
        "overall_status": overall,
        "degraded_methods": degraded,
        "methods": methods,
        "generated_at": generated_at,
        "simulated": batch_id is not None,
    }
