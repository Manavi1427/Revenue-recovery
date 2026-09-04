# Deployment checklist

Repository root is this Git repository. Vercel Root Directory is `app/frontend`; Render Root Directory is `app/backend`.

1. Run backend tests, frontend lint/build, and review `git status`.
2. Provision PostgreSQL and set `DATABASE_URL` only in Render.
3. Create the backend from `render.yaml`; configure `FRONTEND_ORIGINS`, `BACKEND_PUBLIC_URL`, and `RAZORPAY_WEBHOOK_SECRET`; start in Mock Mode.
4. Deploy backend. Build: `pip install -r requirements.txt`. Start: `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`. Health: `/ready`.
5. Verify `/health` and `/ready`; expose `/docs` only if intended.
6. Add `https://<vercel-domain>` to `FRONTEND_ORIGINS` and redeploy backend.
7. Import into Vercel; set Root Directory `app/frontend`, Framework `Next.js`, and `NEXT_PUBLIC_API_BASE_URL=https://<backend-domain>`.
8. Deploy frontend and verify dashboard/API communication.
9. In Razorpay **Test Mode**, set `https://<backend-domain>/webhooks/razorpay`, use the backend webhook secret, and enable only `payment.failed` and `payment.captured`.
10. Test failed/captured events, redeliver both to confirm idempotency, run the hosted smoke test, and rehearse once.
11. Return to Mock Mode for judging if that is the more reliable fallback.

Never use Live Mode or put backend secrets in Vercel/`NEXT_PUBLIC_*`. External deployment, hosted migrations, and webhook changes remain manual.

Safe reset, first as a dry run:

```powershell
cd app/backend
.\venv\Scripts\python.exe scripts/reset_demo_batch.py --batch-id <batch-id>
.\venv\Scripts\python.exe scripts/reset_demo_batch.py --batch-id <batch-id> --confirm
```
