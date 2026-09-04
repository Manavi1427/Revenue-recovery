from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
import random
import re
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import AuditLog, ExperimentGroup, PaymentEvent, RecoveryCase, RecoveryStatus
from demo_batch_config import DemoBatchConfigurationError, get_demo_batch_settings
from execution_config import get_execution_settings
from payment_health_config import get_payment_health_settings
from integrations.mock_payment_link import MockPaymentLinkProvider
from schemas import DemoBatchRequest
from services.case_service import process_failed_payment, process_successful_payment
from services.evaluation_service import evaluate_recovery_case
from services.execution_service import execute_intervention
from services.metrics_service import calculate_overview_metrics
from services.payment_health_service import get_payment_health


FAILURE_WEIGHTS = {
    "incorrect_pin": 30,
    "insufficient_funds": 25,
    "bank_unavailable": 20,
    "expired_card": 15,
    "unknown_failure": 10,
}
FAILURE_FIELDS = {
    "incorrect_pin": {"error_reason": "incorrect_pin", "error_description": "Incorrect PIN"},
    "insufficient_funds": {"error_reason": "insufficient_funds", "error_description": "Insufficient funds"},
    "bank_unavailable": {"error_reason": "bank_unavailable", "error_description": "Bank temporarily unavailable"},
    "expired_card": {"error_reason": "expired_card", "error_description": "Card expired"},
    "unknown_failure": {"error_reason": "unclassified_failure", "error_description": "Unknown payment failure"},
}
AMOUNTS = [49_900, 79_900, 99_900, 149_900, 249_900, 499_900]
PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]

# Synthetic probabilities for a repeatable hackathon demonstration.
# They must not be presented as production Razorpay recovery rates.
RECOVERY_PROBABILITIES = {
    "incorrect_pin": {"holdout": 0.20, "treatment": 0.55},
    "insufficient_funds": {"holdout": 0.08, "treatment": 0.30},
    "bank_unavailable": {"holdout": 0.15, "treatment": 0.45},
    "expired_card": {"holdout": 0.03, "treatment": 0.12},
}
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class DemoBatchDisabled(RuntimeError):
    pass


class DemoBatchNotFound(LookupError):
    pass


class DemoBatchConflict(RuntimeError):
    pass


def calculate_failure_counts(batch_size: int) -> dict[str, int]:
    """Scale the 100-case distribution with largest-remainder allocation."""

    exact = {name: batch_size * weight / 100 for name, weight in FAILURE_WEIGHTS.items()}
    counts = {name: int(value) for name, value in exact.items()}
    remaining = batch_size - sum(counts.values())
    order = sorted(FAILURE_WEIGHTS, key=lambda name: (-(exact[name] - counts[name]), list(FAILURE_WEIGHTS).index(name)))
    for name in order[:remaining]:
        counts[name] += 1
    return counts


def _batch_id(key: str | None) -> str:
    if key is None:
        return str(uuid4())
    normalized = key.strip()
    if not KEY_PATTERN.fullmatch(normalized):
        raise ValueError("idempotency_key contains unsupported characters")
    return str(uuid5(NAMESPACE_URL, f"recoveriq-demo-batch:{normalized}"))


def _metadata(db: Session, batch_id: str) -> dict[str, object] | None:
    first_case = db.scalar(select(RecoveryCase).where(RecoveryCase.batch_id == batch_id))
    if first_case is None:
        return None
    log = db.scalar(select(AuditLog).where(
        AuditLog.recovery_case_id == first_case.id,
        AuditLog.action == "DEMO_BATCH_CASE_CREATED",
    ).order_by(AuditLog.created_at.asc()))
    return log.decision_data if log else None


def get_demo_batch(db: Session, batch_id: str, *, replay: bool = False) -> dict[str, object]:
    metadata = _metadata(db, batch_id)
    if metadata is None:
        raise DemoBatchNotFound("Demo batch not found")
    metrics = calculate_overview_metrics(db, batch_id)
    requested = int(metadata.get("requested_cases", metrics["total_cases"]))
    return {
        "batch_id": batch_id,
        "seed": int(metadata.get("seed", 0)),
        "requested_cases": requested,
        "created_cases": metrics["total_cases"],
        "treatment_cases": metrics["treatment_cases"],
        "holdout_cases": metrics["holdout_cases"],
        "ineligible_cases": metrics["ineligible_cases"],
        "recovered_cases": metrics["recovered_cases"],
        "interventions_attempted": metrics["interventions_attempted"],
        "suppressed_interventions": metrics["suppressed_interventions"],
        "status": "COMPLETED" if metrics["total_cases"] == requested else "INCOMPLETE",
        "simulated": True,
        "metrics": metrics,
        "idempotent_replay": replay,
    }


def _case_specs(batch_id: str, request: DemoBatchRequest) -> list[dict[str, object]]:
    rng = random.Random(request.seed)
    failures = [name for name, count in calculate_failure_counts(request.batch_size).items() for _ in range(count)]
    specs = []
    base_time = datetime.now(timezone.utc).replace(microsecond=0)
    for index, failure in enumerate(failures):
        digest = hashlib.sha256(f"{batch_id}:{index}:{failure}".encode()).hexdigest()[:24]
        specs.append({
            "index": index,
            "failure": failure,
            "amount": rng.choice(AMOUNTS),
            "method": "upi" if index < round(request.batch_size * 0.70) else PAYMENT_METHODS[1 + (index % 3)],
            "payment_id": f"pay_batch_{digest}",
            "order_id": f"order_batch_{digest}",
            "event_id": f"evt_batch_failed_{digest}",
            "failed_at": base_time - timedelta(seconds=rng.randint(43_200, 86_400)),
        })
    return specs


def _add_background_successes(
    db: Session, batch_id: str, specs: list[dict[str, object]]
) -> None:
    """Add unique successful demo attempts needed for a valid health denominator."""

    settings = get_payment_health_settings()
    failed_counts = {
        method: sum(spec["method"] == method for spec in specs)
        for method in PAYMENT_METHODS
    }
    events: list[PaymentEvent] = []
    base_time = max(spec["failed_at"] for spec in specs)
    for method in PAYMENT_METHODS:
        if method == "upi":
            continue  # Default demo traffic intentionally makes UPI degraded.
        failed = failed_counts[method]
        limit = settings.baselines[method] + settings.threshold
        required_total = max(settings.minimum_attempts, math.floor(failed / limit) + 1)
        success_count = max(0, required_total - failed)
        for index in range(success_count):
            digest = hashlib.sha256(
                f"{batch_id}:background:{method}:{index}".encode()
            ).hexdigest()[:24]
            payment_id = f"pay_background_{digest}"
            events.append(PaymentEvent(
                event_id=f"evt_background_captured_{digest}",
                event_type="payment.captured",
                batch_id=batch_id,
                payment_id=payment_id,
                amount=AMOUNTS[index % len(AMOUNTS)],
                currency="INR",
                payment_method=method,
                normalized_payload={"id": payment_id, "method": method},
                raw_payload={"event": "payment.captured", "demo": True,
                             "background_traffic": True, "batch_id": batch_id},
                occurred_at=base_time - timedelta(seconds=index + 1),
            ))
    db.add_all(events)
    db.flush()


def run_demo_batch(db: Session, request: DemoBatchRequest) -> dict[str, object]:
    settings = get_demo_batch_settings()
    if not settings.enabled:
        raise DemoBatchDisabled("Demo batch execution is disabled")
    batch_id = _batch_id(request.idempotency_key)
    existing = _metadata(db, batch_id)
    if existing is not None:
        result = get_demo_batch(db, batch_id, replay=True)
        if result["status"] != "COMPLETED":
            raise DemoBatchConflict("A batch with this idempotency key is incomplete")
        return result

    specs = _case_specs(batch_id, request)
    cases: list[tuple[RecoveryCase, dict[str, object]]] = []
    try:
        db.info["demo_batch_fast"] = True
        _add_background_successes(db, batch_id, specs)
        for spec in specs:
            payment = {
                "id": spec["payment_id"], "order_id": spec["order_id"],
                "amount": spec["amount"], "currency": "INR", "method": spec["method"],
                **FAILURE_FIELDS[str(spec["failure"])],
            }
            raw = {"event": "payment.failed", "demo": True, "batch_id": batch_id}
            case = process_failed_payment(
                db, str(spec["event_id"]), "payment.failed", payment, raw,
                simulated_at=spec["failed_at"], commit_changes=False,
                batch_id=batch_id, assume_new=True,
            )
            case.batch_id = batch_id
            db.add(case)
            cases.append((case, spec))

        eligible = [(case, spec) for case, spec in cases if case.status != RecoveryStatus.HUMAN_REVIEW]
        assignment_rng = random.Random(request.seed)
        assignment_rng.shuffle(eligible)
        treatment_count = round(len(eligible) * request.treatment_percent / 100)
        treatment_ids = {case.id for case, _ in eligible[:treatment_count]}
        for case, spec in cases:
            if case.status == RecoveryStatus.HUMAN_REVIEW:
                group, action = ExperimentGroup.INELIGIBLE, "EXPERIMENT_INELIGIBLE"
            elif case.id in treatment_ids:
                group, action = ExperimentGroup.TREATMENT, "EXPERIMENT_TREATMENT_ASSIGNED"
            else:
                group, action = ExperimentGroup.HOLDOUT, "EXPERIMENT_HOLDOUT_ASSIGNED"
            case.experiment_group = group.value
            common = {"batch_id": batch_id, "experiment_group": group.value, "seed": request.seed, "failure_category": spec["failure"]}
            db.add(AuditLog(recovery_case_id=case.id, action="DEMO_BATCH_CASE_CREATED", actor="SIMULATOR", previous_status=case.status, new_status=case.status, decision_data={**common, "requested_cases": request.batch_size, "treatment_percent": request.treatment_percent}))
            db.add(AuditLog(recovery_case_id=case.id, action=action, actor="SIMULATOR", previous_status=case.status, new_status=case.status, decision_data=common))
        db.flush()

        provider = MockPaymentLinkProvider(get_execution_settings().backend_public_url)
        health = get_payment_health(db, batch_id)
        health_by_method = {
            str(item["payment_method"]): item for item in health["methods"]
        }
        successful_treatment: set[str] = set()
        for case, _ in cases:
            if case.experiment_group != ExperimentGroup.TREATMENT.value:
                continue
            evaluation = evaluate_recovery_case(
                db, case.id, commit_changes=False,
                method_health_by_method=health_by_method,
                known_case=case,
                known_event=next(event for event in case.payment_events if event.event_type == "payment.failed"),
            )
            if evaluation.intervention is not None and evaluation.policy.allowed:
                result = execute_intervention(
                    db, evaluation.intervention.id, provider=provider,
                    commit_changes=False,
                    known_case=case, known_intervention=evaluation.intervention,
                    method_health=health_by_method.get(str(case.payment_method or "").lower()),
                )
                if result.case_status == RecoveryStatus.CONTACTED:
                    successful_treatment.add(case.id)

        outcome_rng = random.Random(request.seed + 1_000_003)
        for case, spec in cases:
            failure = str(spec["failure"])
            if failure not in RECOVERY_PROBABILITIES:
                continue
            if case.experiment_group == ExperimentGroup.TREATMENT.value:
                if case.id not in successful_treatment:
                    continue
                outcome_type, probability = "SIMULATED_TREATMENT_RECOVERY", RECOVERY_PROBABILITIES[failure]["treatment"]
            elif case.experiment_group == ExperimentGroup.HOLDOUT.value:
                outcome_type, probability = "SIMULATED_ORGANIC_RECOVERY", RECOVERY_PROBABILITIES[failure]["holdout"]
            else:
                continue
            if outcome_rng.random() >= probability:
                continue
            recovered_at = spec["failed_at"] + timedelta(seconds=outcome_rng.randint(300, 43_200))
            payment = {"id": case.payment_id, "order_id": case.order_id, "amount": case.amount, "currency": case.currency}
            digest = hashlib.sha256(f"{batch_id}:{case.id}:captured".encode()).hexdigest()[:24]
            process_successful_payment(db, f"evt_batch_captured_{digest}", "payment.captured", payment, {"event": "payment.captured", "demo": True, "batch_id": batch_id}, simulated_at=recovered_at, commit_changes=False, batch_id=batch_id, known_case=case)
            db.add(AuditLog(recovery_case_id=case.id, action=outcome_type, actor="SIMULATOR", previous_status=RecoveryStatus.RECOVERED, new_status=RecoveryStatus.RECOVERED, decision_data={"batch_id": batch_id, "failure_category": failure, "synthetic_probability": probability}))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DemoBatchConflict(
            "A batch with this idempotency key is already running or complete"
        ) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("demo_batch_fast", None)
    return get_demo_batch(db, batch_id)
