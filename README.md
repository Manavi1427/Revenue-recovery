# RecoverIQ

RecoverIQ turns failed payments into policy-controlled recovery cases. It diagnoses failures, scores recoverability with an optional ML model and deterministic fallback, creates auditable recovery interventions, and measures incremental recovery against a holdout group.

## What makes it useful

- Rule/ML scoring continues safely when the optional model is unavailable.
- Deterministic policy checks—not a model—control financial actions.
- Treatment and holdout groups measure incremental lift, not just gross recovery.
- Payment Health suppresses unsuitable same-method retries during degradation.
- Mock-first Payment Links keep the demo usable without Razorpay or network access.

Architecture: `Next.js → FastAPI → scoring/policy services → mock or Razorpay Test provider → PostgreSQL → metrics and audit timeline`.

## Local setup

```powershell
cd app/backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item ..\..\.env.example .env
# Configure DATABASE_URL, then:
alembic upgrade head
uvicorn main:app --reload --port 8000
```

In another terminal:

```powershell
cd app/frontend
npm ci
Copy-Item ..\..\.env.example .env.local
# Set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

Validation:

```powershell
cd app/backend; .\venv\Scripts\python.exe -m pytest
cd app/frontend; npm run lint; npm run build
```

## Environment

- `APP_ENV`: `development` or `production`.
- `DATABASE_URL`: SQLAlchemy URL; `postgres://` is normalized safely.
- `FRONTEND_ORIGINS`: comma-separated explicit CORS origins.
- `RAZORPAY_MODE`: `mock` or `test`; live mode is rejected.
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`: Test Mode credentials only.
- `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_WEBHOOKS_ENABLED`: backend webhook configuration.
- `BACKEND_PUBLIC_URL`; `MESSAGE_MODE=template`.
- `DEMO_BATCH_ENABLED`, `DEMO_BATCH_SIZE`, `DEMO_BATCH_SEED`, `DEMO_TREATMENT_PERCENT`.
- `PAYMENT_HEALTH_ENABLED` and the `PAYMENT_HEALTH_*` window, threshold, and baseline settings.
- `NEXT_PUBLIC_API_BASE_URL`: public backend URL. Never put secrets in `NEXT_PUBLIC_*`.
- `NEXT_PUBLIC_DEMO_MODE`: enables demo capture controls.

## Demo and API

Open `/dashboard`, run the seeded batch, show revenue at risk and experiment groups, open a treatment case, explain diagnosis/score/policy, show its Payment Link and message preview, simulate capture, then show `RECOVERED`, cancelled actions, and lift. Seeded results are simulated hackathon data, not production rates.

Important routes: `/health`, `/ready`, `/metrics/overview`, `/metrics/payment-health`, `/cases`, `/cases/{id}`, `/cases/{id}/timeline`, `/demo/batches`, `/interventions/{id}/execute`, and `/webhooks/razorpay`.

Treatment recovery rate is recovered treatment value divided by treatment exposure. Holdout recovery rate is organic recovered holdout value divided by holdout exposure. Incremental lift is treatment rate minus holdout rate.

Webhook signatures use the untouched raw body, event IDs are idempotent, recovered and holdout cases have stopping rules, decisions are audited, and Mock Mode makes no Razorpay network call.

See [DEMO.md](DEMO.md) and [deployment instructions](docs/deployment.md).
