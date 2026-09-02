from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import AuditLog, Intervention, RecoveryCase, RecoveryStatus
from execution_config import get_execution_settings
from integrations.mock_payment_link import MockPaymentLinkProvider
from integrations.payment_link_provider import (
    PaymentLinkProvider, PaymentLinkProviderError, PaymentLinkRequest, PaymentLinkResult,
)
from integrations.razorpay_payment_link import RazorpayTestPaymentLinkProvider
from services.message_service import RecoveryMessage, generate_recovery_message
from services.recovery_actions import RecoveryAction


logger = logging.getLogger(__name__)
EXECUTABLE_ACTIONS = {
    RecoveryAction.IMMEDIATE_RETRY, RecoveryAction.RETRY_LATER,
    RecoveryAction.CREATE_PAYMENT_LINK, RecoveryAction.SUGGEST_ALTERNATIVE_METHOD,
    RecoveryAction.REQUEST_NEW_METHOD,
}
SUPPORTED_CURRENCIES = {"INR"}


class ExecutionNotFound(LookupError):
    pass


class ExecutionConflict(RuntimeError):
    pass


class ExecutionValidationError(ValueError):
    pass


class ExecutionProviderFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    case_id: str
    case_status: RecoveryStatus
    intervention_id: str
    action_type: RecoveryAction
    provider: str
    mode: str
    payment_link: PaymentLinkResult
    message: RecoveryMessage
    idempotent_replay: bool


def _provider_result_data(result: PaymentLinkResult) -> dict[str, object]:
    return {
        "name": result.provider, "mode": result.mode,
        "payment_link_id": result.payment_link_id,
        "reference_id": result.reference_id,
        "short_url": result.short_url, "status": result.status,
        "created_at": result.created_at.isoformat(),
    }


def _restore_result(case: RecoveryCase, intervention: Intervention) -> ExecutionResult:
    payload = intervention.result_payload or {}
    provider = payload.get("provider", {})
    message = payload.get("message", {})
    try:
        link = PaymentLinkResult(
            provider=str(provider["name"]), mode=str(provider["mode"]),
            payment_link_id=str(provider["payment_link_id"]),
            reference_id=str(provider["reference_id"]), short_url=str(provider["short_url"]),
            status=str(provider["status"]), created_at=datetime.fromisoformat(str(provider["created_at"])),
        )
        preview = RecoveryMessage(
            title=str(message["title"]), body=str(message["body"]),
            cta_label=str(message["cta_label"]), payment_url=str(message["payment_url"]),
            language=str(message["language"]), source=str(message["source"]),
        )
        action = RecoveryAction(intervention.action_type)
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionConflict("Stored execution result is incomplete") from exc
    return ExecutionResult(case.id, case.status, intervention.id, action, link.provider, link.mode, link, preview, True)


def _load_locked(db: Session, intervention_id: str) -> tuple[Intervention, RecoveryCase]:
    intervention = db.scalar(select(Intervention).where(Intervention.id == intervention_id).with_for_update())
    if intervention is None:
        raise ExecutionNotFound("Intervention not found")
    case = db.scalar(select(RecoveryCase).where(RecoveryCase.id == intervention.recovery_case_id).with_for_update())
    if case is None:
        raise ExecutionNotFound("Recovery case not found")
    return intervention, case


def _validate_pending(intervention: Intervention, case: RecoveryCase) -> RecoveryAction:
    if intervention.executed_at is not None and intervention.successful and intervention.result_payload:
        return RecoveryAction(intervention.action_type)
    if intervention.cancelled_at is not None:
        raise ExecutionConflict("Cancelled interventions cannot execute")
    if case.status in {RecoveryStatus.RECOVERED, RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED, RecoveryStatus.HUMAN_REVIEW}:
        raise ExecutionConflict(f"Case status {case.status.value} blocks execution")
    if case.status != RecoveryStatus.ACTION_SCHEDULED:
        raise ExecutionConflict("Case must be ACTION_SCHEDULED before execution")
    try:
        action = RecoveryAction(intervention.action_type)
    except ValueError as exc:
        raise ExecutionValidationError("Intervention action is not approved") from exc
    if action not in EXECUTABLE_ACTIONS:
        raise ExecutionConflict(f"Action {action.value} cannot execute")
    payload = intervention.action_payload or {}
    if payload.get("status") == "IN_PROGRESS":
        raise ExecutionConflict("Intervention execution is already in progress")
    if payload.get("status") not in {"PENDING_EXECUTION", "FAILED"} or not intervention.scheduled_at:
        raise ExecutionConflict("Intervention is not an approved pending action")
    if isinstance(case.amount, bool) or not isinstance(case.amount, int) or case.amount <= 0:
        raise ExecutionValidationError("Case amount must be a positive integer in paise")
    if case.currency not in SUPPORTED_CURRENCIES:
        raise ExecutionValidationError("Case currency is not supported")
    return action


def _configured_provider() -> PaymentLinkProvider:
    settings = get_execution_settings(require_test_credentials=True)
    if settings.razorpay_mode == "mock":
        return MockPaymentLinkProvider(settings.backend_public_url)
    return RazorpayTestPaymentLinkProvider(
        settings.razorpay_key_id or "", settings.razorpay_key_secret or "",
    )


def execute_intervention(
    db: Session, intervention_id: str, provider: PaymentLinkProvider | None = None,
) -> ExecutionResult:
    """Execute one approved intervention with stopping checks and idempotency."""

    intervention, case = _load_locked(db, intervention_id)
    if case.status in {
        RecoveryStatus.RECOVERED, RecoveryStatus.EXHAUSTED,
        RecoveryStatus.SUPPRESSED, RecoveryStatus.HUMAN_REVIEW,
    }:
        raise ExecutionConflict(f"Case status {case.status.value} blocks execution")
    if intervention.executed_at is not None and intervention.successful and intervention.result_payload:
        return _restore_result(case, intervention)
    action = _validate_pending(intervention, case)
    previous_status = case.status
    action_payload = dict(intervention.action_payload or {})
    action_payload["status"] = "IN_PROGRESS"
    intervention.action_payload = action_payload
    db.add(AuditLog(
        recovery_case_id=case.id, action="INTERVENTION_EXECUTION_STARTED", actor="SYSTEM",
        previous_status=previous_status, new_status=previous_status,
        decision_data={"intervention_id": intervention.id, "action_type": action.value},
    ))
    # Commit the claim before a provider call so another request cannot start it again.
    db.commit()

    request = PaymentLinkRequest(case.id, intervention.id, case.amount, case.currency)
    try:
        active_provider = provider or _configured_provider()
        link = active_provider.create_payment_link(request)
    except Exception as exc:
        db.rollback()
        intervention, case = _load_locked(db, intervention_id)
        failed_payload = dict(intervention.action_payload or {})
        failed_payload["status"] = "FAILED"
        intervention.action_payload = failed_payload
        intervention.successful = False
        intervention.result_payload = {
            "execution_status": "FAILED",
            "error": {"code": "PAYMENT_LINK_PROVIDER_ERROR", "message": "The payment link could not be created."},
        }
        db.add(AuditLog(
            recovery_case_id=case.id, action="INTERVENTION_EXECUTION_FAILED", actor="SYSTEM",
            previous_status=case.status, new_status=case.status,
            decision_data={"intervention_id": intervention.id, "error_code": "PAYMENT_LINK_PROVIDER_ERROR"},
        ))
        db.commit()
        logger.warning("Payment-link provider failed for intervention %s: %s", intervention_id, type(exc).__name__)
        raise ExecutionProviderFailure("The payment link could not be created") from exc

    db.expire_all()
    intervention, case = _load_locked(db, intervention_id)
    if case.status == RecoveryStatus.RECOVERED:
        intervention.cancelled_at = datetime.now(timezone.utc)
        stopped_payload = dict(intervention.action_payload or {})
        stopped_payload["status"] = "STOPPED"
        intervention.action_payload = stopped_payload
        db.add(AuditLog(
            recovery_case_id=case.id, action="EXECUTION_STOPPED", actor="SYSTEM",
            previous_status=RecoveryStatus.RECOVERED, new_status=RecoveryStatus.RECOVERED,
            decision_data={"intervention_id": intervention.id, "reason": "CASE_RECOVERED_DURING_EXECUTION"},
        ))
        db.commit()
        raise ExecutionConflict("Case recovered during execution; message generation stopped")
    if case.status != RecoveryStatus.ACTION_SCHEDULED:
        db.rollback()
        raise ExecutionConflict("Case status changed before execution completed")

    message = generate_recovery_message(
        action=action, amount=case.amount, currency=case.currency,
        payment_url=link.short_url, case_id=case.id,
    )
    provider_data = _provider_result_data(link)
    intervention.result_payload = {
        "execution_status": "COMPLETED",
        "provider": provider_data,
        "message": asdict(message),
    }
    finished_at = datetime.now(timezone.utc)
    intervention.executed_at = finished_at
    intervention.successful = True
    intervention.channel = "MESSAGE_PREVIEW"
    completed_payload = dict(intervention.action_payload or {})
    completed_payload["status"] = "COMPLETED"
    intervention.action_payload = completed_payload
    case.status = RecoveryStatus.CONTACTED
    for audit_action, data in (
        ("PAYMENT_LINK_CREATED", {"intervention_id": intervention.id, "provider": link.provider, "mode": link.mode, "reference_id": link.reference_id}),
        ("MESSAGE_GENERATED", {"intervention_id": intervention.id, "source": message.source}),
        ("INTERVENTION_EXECUTED", {"intervention_id": intervention.id, "action_type": action.value}),
    ):
        db.add(AuditLog(
            recovery_case_id=case.id, action=audit_action, actor="SYSTEM",
            previous_status=previous_status,
            new_status=RecoveryStatus.CONTACTED if audit_action == "INTERVENTION_EXECUTED" else previous_status,
            decision_data=data,
        ))
    db.commit()
    db.refresh(case)
    db.refresh(intervention)
    return ExecutionResult(case.id, case.status, intervention.id, action, link.provider, link.mode, link, message, False)
