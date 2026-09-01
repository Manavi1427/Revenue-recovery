import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import cases, metrics, scoring, simulator, webhooks



load_dotenv()

app = FastAPI(title="RecoverIQ API")

frontend_url = os.getenv("FRONTEND_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url] if frontend_url else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "recoveriq-api"}




app.include_router(webhooks.router)
app.include_router(cases.router)
app.include_router(simulator.router)
app.include_router(metrics.router)
app.include_router(scoring.router)
