import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db_session import get_db
from services.case_service import process_failed_payment, process_successful_payment


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing webhook signature")
    if not secret:
        logger.error("Razorpay webhook secret is not configured")
        raise HTTPException(status_code=500, detail="Webhook is not configured")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Malformed JSON")

    event_type = payload.get("event")
    event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(body).hexdigest()
    payment_data = payload.get("payload", {}).get("payment", {}).get("entity")
    try:
        if event_type == "payment.failed" and isinstance(payment_data, dict):
            case = process_failed_payment(db, event_id, event_type, payment_data, payload)
            return {"status": "processed", "case_id": case.id}
        if event_type in {"payment.captured", "order.paid"} and isinstance(payment_data, dict):
            case = process_successful_payment(db, event_id, event_type, payment_data, payload)
            return {"status": "processed", "case_id": case.id if case else None}
        return {"status": "ignored", "event": event_type}
    except Exception:
        db.rollback()
        logger.exception("Razorpay event processing failed", extra={"event_type": event_type})
        raise HTTPException(status_code=500, detail="Event processing failed")
