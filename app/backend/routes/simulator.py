from enum import Enum
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db_session import get_db
from services.case_service import process_failed_payment, process_successful_payment


router = APIRouter(prefix="/simulator", tags=["development simulator"])

FAILURES = {
    "incorrect_pin": {"error_reason": "incorrect_pin", "error_description": "Incorrect PIN"},
    "insufficient_funds": {"error_reason": "insufficient_funds"},
    "bank_unavailable": {"error_reason": "bank_unavailable"},
    "expired_card": {"error_reason": "expired_card"},
    "unknown_failure": {"error_reason": "unclassified_failure"},
}


class FailureType(str, Enum):
    incorrect_pin = "incorrect_pin"
    insufficient_funds = "insufficient_funds"
    bank_unavailable = "bank_unavailable"
    expired_card = "expired_card"
    unknown_failure = "unknown_failure"


@router.post("/payment-failed")
def simulate_failure(
    failure_type: FailureType = FailureType.incorrect_pin,
    db: Session = Depends(get_db),
):
    suffix = uuid4().hex
    payment = {
        "id": f"pay_demo_{suffix}",
        "order_id": f"order_demo_{suffix}",
        "amount": 249900,
        "currency": "INR",
        "method": "card",
        **FAILURES[failure_type.value],
    }
    case = process_failed_payment(db, f"evt_demo_failed_{suffix}", "payment.failed", payment, {"event": "payment.failed", "payload": {"payment": {"entity": payment}}})
    return {
        "payment_id": case.payment_id,
        "order_id": case.order_id,
        "case_id": case.id,
        "case_status": case.status,
        "diagnosis": case.diagnosis,
        "recommended_action": case.recommended_action,
    }


@router.post("/payment-success/{payment_id}")
def simulate_success(payment_id: str, order_id: str | None = None, db: Session = Depends(get_db)):
    suffix = uuid4().hex
    payment = {"id": payment_id, "order_id": order_id, "amount": 249900, "currency": "INR"}
    case = process_successful_payment(db, f"evt_demo_success_{suffix}", "payment.captured", payment, {"event": "payment.captured", "payload": {"payment": {"entity": payment}}})
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return {"payment_id": payment_id, "case_id": case.id, "case_status": case.status}
