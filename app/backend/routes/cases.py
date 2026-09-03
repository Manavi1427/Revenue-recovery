from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import AuditLog, RecoveryCase
from db_session import get_db
from schemas import AuditLogRead, RecoveryCaseRead


router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[RecoveryCaseRead])
def list_cases(batch_id: str | None = None, db: Session = Depends(get_db)):
    statement = select(RecoveryCase)
    if batch_id is not None:
        statement = statement.where(RecoveryCase.batch_id == batch_id)
    return db.scalars(statement.order_by(RecoveryCase.opened_at.desc())).all()


@router.get("/{case_id}", response_model=RecoveryCaseRead)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return case


@router.get("/{case_id}/timeline", response_model=list[AuditLogRead])
def get_timeline(case_id: str, db: Session = Depends(get_db)):
    if db.get(RecoveryCase, case_id) is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")
    return db.scalars(select(AuditLog).where(
        AuditLog.recovery_case_id == case_id
    ).order_by(AuditLog.created_at.asc())).all()
