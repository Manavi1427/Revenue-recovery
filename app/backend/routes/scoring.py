from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import RecoveryCase
from db_session import get_db
from ml.predictor import get_model_status
from schemas import ScoringResponse
from services.scoring_service import score_recovery_case


router = APIRouter(tags=["scoring"])


@router.post("/cases/{case_id}/score", response_model=ScoringResponse)
def score_case(case_id: str, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    result = score_recovery_case(db, case)
    return {"case_id": case.id, **result.__dict__}


@router.get("/model/status")
def model_status():
    return get_model_status()
