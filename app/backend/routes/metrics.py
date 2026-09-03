from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db_session import get_db
from payment_health_config import PaymentHealthConfigurationError
from schemas import OverviewMetricsResponse, PaymentHealthResponse
from services.metrics_service import calculate_overview_metrics
from services.payment_health_service import (
    PaymentHealthBatchNotFound,
    PaymentHealthDisabled,
    get_payment_health,
)


router = APIRouter(prefix="/metrics", tags=["metrics"])
@router.get("/overview", response_model=OverviewMetricsResponse)
def overview(batch_id: str | None = None, db: Session = Depends(get_db)):
    return calculate_overview_metrics(db, batch_id)


@router.get("/payment-health", response_model=PaymentHealthResponse)
def payment_health(batch_id: str | None = None, db: Session = Depends(get_db)):
    try:
        return get_payment_health(db, batch_id)
    except PaymentHealthBatchNotFound as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaymentHealthDisabled as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PaymentHealthConfigurationError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc)) from exc
