from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db_session import get_db
from demo_batch_config import DemoBatchConfigurationError, get_demo_batch_settings
from schemas import DemoBatchRequest, DemoBatchResponse
from services.demo_batch_service import (
    DemoBatchConflict,
    DemoBatchDisabled,
    DemoBatchNotFound,
    get_demo_batch,
    run_demo_batch,
)


router = APIRouter(prefix="/demo/batches", tags=["demo batches"])


@router.post("", response_model=DemoBatchResponse)
def create_batch(request: DemoBatchRequest, db: Session = Depends(get_db)):
    try:
        return run_demo_batch(db, request)
    except DemoBatchDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DemoBatchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DemoBatchConfigurationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Demo batch processing failed safely"
        ) from exc


@router.get("/{batch_id}", response_model=DemoBatchResponse)
def read_batch(batch_id: str, db: Session = Depends(get_db)):
    try:
        settings = get_demo_batch_settings()
        if not settings.enabled:
            raise DemoBatchDisabled("Demo batch endpoints are disabled")
        return get_demo_batch(db, batch_id)
    except DemoBatchDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DemoBatchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DemoBatchConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
