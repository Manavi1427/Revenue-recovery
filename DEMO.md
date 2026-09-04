# RecoverIQ three-minute demo

## Before the demo

- Verify `/health`, `/ready`, frontend, database, and the Mock/Test label.
- From `app/backend`, run `python scripts/smoke_demo.py --base-url http://localhost:8000 --seed 42 --idempotency-key final-judging-demo`.
- Keep the returned batch ID and one suitable treatment case open.
- Open dashboard/case tabs, close secret-bearing terminals, disable notifications, and keep Mock Mode locally available.

## Script

- **0:00–0:20 — Problem:** “Failed payments do not all need the same recovery action. RecoverIQ diagnoses each failure, estimates recoverability and applies policy-controlled interventions.”
- **0:20–0:45 — Revenue at risk:** show money at risk, active cases, treatment, and holdout.
- **0:45–1:15 — Failed case:** show diagnosis, score, score source/fallback, and action.
- **1:15–1:40 — Policy:** show checks, Payment Health, and audit trail. “The model does not directly control financial actions. Every action is bounded by deterministic policies.”
- **1:40–2:10 — Intervention:** show link, message preview, mode label, and no external delivery.
- **2:10–2:30 — Recovery:** simulate capture; show `RECOVERED`, `closed_at`, cancellation, and stopping rule.
- **2:30–3:00 — Measurement:** show recovered value, treatment/holdout rates, and lift. “RecoverIQ does not only report money recovered. It measures the incremental revenue created by policy-controlled recovery against a holdout group.”

## Judge questions

- **Why holdout?** It estimates organic recovery and makes incremental impact measurable.
- **Why not let an LLM act?** Financial actions require deterministic, testable limits; the model only supplies evidence.
- **ML failure?** Rules return a score and processing continues with an audit entry.
- **Razorpay unavailable?** Mock Mode creates deterministic local links without a network call.
- **Duplicate intervention?** Event uniqueness, pending-action checks, locks, and saved-result replay prevent it.
- **Recovered case?** Terminal-state checks block new actions and audit the stop.
- **Real rates?** No; seeded results are simulated hackathon data.
- **Scale?** Add background workers and observability while retaining transactional idempotency.
- **Payment Health?** It avoids repeating a currently degraded method.
- **Customer data sent to the model?** The local prototype uses normalized payment/failure features; no generative model receives messages or credentials.

## Fallback assets

Local sequence: PostgreSQL → FastAPI → Next.js → Mock Mode → seeded smoke test. Expect 100 cases with treatment, holdout, and ineligible groups; UPI is intentionally degraded. Record a suitable case ID only after creation.

Screenshot checklist: dashboard metrics; lift; Payment Health; diagnosis/score; policy; link/message; recovered state; timeline. Hide secrets and personal data.

Backup recording shot list (60–90 seconds): dashboard → case → policy → intervention → recovery → lift. No screenshots or recording are claimed as created.
