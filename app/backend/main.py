from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from routes import cases, demo_batches, evaluations, executions, metrics, scoring, simulator, webhooks
from db_session import engine
from ml.predictor import get_model_status
from runtime_config import frontend_origins, validate_production_config



load_dotenv()
validate_production_config()

app = FastAPI(title="RecoverIQ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Razorpay-Signature", "X-Razorpay-Event-Id"],
)


@app.get("/health")
def health() -> dict[str, object]:
    model = get_model_status()
    return {"status": "ok", "service": "recoveriq-api", "version": "1.0.0",
            "razorpay_mode": __import__("os").getenv("RAZORPAY_MODE", "mock").lower(),
            "model_status": "available" if model["model_available"] else "rules_fallback",
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "service": "recoveriq-api", "database": "unavailable"})
    return {"status": "ready", "service": "recoveriq-api", "database": "connected"}




app.include_router(webhooks.router)
app.include_router(cases.router)
app.include_router(simulator.router)
app.include_router(metrics.router)
app.include_router(scoring.router)
app.include_router(evaluations.router)
app.include_router(executions.router)
app.include_router(demo_batches.router)
