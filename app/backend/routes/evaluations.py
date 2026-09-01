from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import Intervention, RecoveryCase
from db_session import get_db
from schemas import EvaluationResponse, InterventionSummary
from services.evaluation_service import EvaluationCaseNotFound, evaluate_recovery_case
from services.recovery_actions import (
    DECISION_VERSION,
    HIGH_VALUE_REVIEW_THRESHOLD,
    MAX_INTERVENTIONS_PER_CASE,
    MIN_AUTOMATIC_SCORE,
    POLICY_VERSION,
)


router = APIRouter(tags=["evaluations"])


@router.post("/cases/{case_id}/evaluate", response_model=EvaluationResponse)
def evaluate_case(case_id: str, db: Session = Depends(get_db)):
    try:
        return evaluate_recovery_case(db, case_id)
    except EvaluationCaseNotFound:
        raise HTTPException(status_code=404, detail="Recovery case not found")


@router.get("/cases/{case_id}/interventions", response_model=list[InterventionSummary])
def list_interventions(case_id: str, db: Session = Depends(get_db)):
    if db.get(RecoveryCase, case_id) is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return db.scalars(select(Intervention).where(
        Intervention.recovery_case_id == case_id
    ).order_by(Intervention.created_at.desc())).all()


@router.get("/policies/config")
def policy_config():
    return {
        "max_interventions_per_case": MAX_INTERVENTIONS_PER_CASE,
        "minimum_automatic_score": MIN_AUTOMATIC_SCORE,
        "high_value_review_threshold": HIGH_VALUE_REVIEW_THRESHOLD,
        "currency_unit": "paise",
        "decision_version": DECISION_VERSION,
        "policy_version": POLICY_VERSION,
    }
