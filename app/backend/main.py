import os
import hmac
import hashlib

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware



load_dotenv()

app = FastAPI(title="RecoverIQ API")

frontend_url = os.getenv("FRONTEND_URL")
webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "recoveriq-api"}




@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):

    body = await request.body()

    signature = request.headers.get("X-Razorpay-Signature")

    expected_signature = hmac.new(
        webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature or ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook signature"
        )

    payload = await request.json()

    print("Event:", payload.get("event"))

    return {"status": "ok"}