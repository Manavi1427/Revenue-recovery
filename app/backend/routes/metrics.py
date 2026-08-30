from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import RecoveryCase, RecoveryStatus
from db_session import get_db


router = APIRouter(prefix="/metrics", tags=["metrics"])
TERMINAL = (RecoveryStatus.RECOVERED, RecoveryStatus.EXHAUSTED, RecoveryStatus.SUPPRESSED)


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(RecoveryCase)) or 0
    active = db.scalar(select(func.count()).select_from(RecoveryCase).where(RecoveryCase.status.not_in(TERMINAL))) or 0
    recovered = db.scalar(select(func.count()).select_from(RecoveryCase).where(RecoveryCase.status == RecoveryStatus.RECOVERED)) or 0
    at_risk = db.scalar(select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(RecoveryCase.status != RecoveryStatus.RECOVERED)) or 0
    recovered_amount = db.scalar(select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(RecoveryCase.status == RecoveryStatus.RECOVERED)) or 0
    return {"total_cases": total, "active_cases": active, "recovered_cases": recovered, "money_at_risk": at_risk, "recovered_amount": recovered_amount}
