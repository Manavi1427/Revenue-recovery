from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import Intervention
from db_session import get_db
from execution_config import ExecutionConfigurationError, get_execution_settings
from schemas import InterventionExecutionResponse, RazorpayIntegrationStatusResponse
from services.execution_service import (
    ExecutionConflict, ExecutionNotFound, ExecutionProviderFailure,
    ExecutionValidationError, execute_intervention,
)


router = APIRouter(tags=["execution"])


@router.post("/interventions/{intervention_id}/execute", response_model=InterventionExecutionResponse)
def execute(intervention_id: str, db: Session = Depends(get_db)):
    try:
        return execute_intervention(db, intervention_id)
    except ExecutionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ExecutionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ExecutionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (ExecutionProviderFailure, ExecutionConfigurationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/integrations/razorpay/status", response_model=RazorpayIntegrationStatusResponse)
def integration_status():
    try:
        settings = get_execution_settings()
    except ExecutionConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    configured = settings.razorpay_mode == "mock" or settings.test_credentials_configured
    return {
        "mode": settings.razorpay_mode,
        "configured": configured,
        "payment_link_execution_available": configured,
    }


@router.get("/demo/payment-links/{intervention_id}")
def demo_payment_link(intervention_id: str, db: Session = Depends(get_db)):
    try:
        settings = get_execution_settings()
    except ExecutionConfigurationError:
        raise HTTPException(status_code=404, detail="Mock payment page is unavailable")
    if settings.razorpay_mode != "mock":
        raise HTTPException(status_code=404, detail="Mock payment page is unavailable")
    intervention = db.get(Intervention, intervention_id)
    if intervention is None or intervention.recovery_case is None:
        raise HTTPException(status_code=404, detail="Mock payment link not found")
    case = intervention.recovery_case
    return {
        "mock": True,
        "message": "This is a mock payment page; no payment has occurred.",
        "case_id": case.id,
        "intervention_id": intervention.id,
        "reference_id": f"recoveriq_case_{case.id}_intervention_{intervention.id}",
        "amount": case.amount,
        "currency": case.currency,
        "next_step": "Use the captured-payment simulator to demonstrate recovery.",
    }
