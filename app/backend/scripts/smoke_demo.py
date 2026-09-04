from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import requests


def check(condition: bool, message: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the non-destructive RecoverIQ demo smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--treatment-percent", type=int, default=80)
    parser.add_argument("--idempotency-key", default=None)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    key = args.idempotency_key or f"smoke-{uuid4()}"
    try:
        health = requests.get(f"{base}/health", timeout=15)
        check(health.ok and health.json().get("status") == "ok", "API health")
        response = requests.post(f"{base}/demo/batches", json={"seed": args.seed, "batch_size": args.batch_size, "treatment_percent": args.treatment_percent, "idempotency_key": key}, timeout=600)
        response.raise_for_status()
        batch = response.json()
        batch_id = batch["batch_id"]
        check(batch["created_cases"] == args.batch_size, f"{args.batch_size} recovery cases")
        metrics = requests.get(f"{base}/metrics/overview", params={"batch_id": batch_id}, timeout=30).json()
        health_data = requests.get(f"{base}/metrics/payment-health", params={"batch_id": batch_id}, timeout=30)
        health_data.raise_for_status()
        cases = requests.get(f"{base}/cases", params={"batch_id": batch_id}, timeout=30).json()
        groups = {item.get("experiment_group") for item in cases}
        check({"TREATMENT", "HOLDOUT", "INELIGIBLE"}.issubset(groups), "Treatment, holdout, and ineligible groups present")
        check(any(item["status"] == "RECOVERED" for item in cases), "Recovered case present")
        required = {"money_at_risk", "recovered_amount", "treatment_recovery_rate", "holdout_recovery_rate", "incremental_lift"}
        check(required <= metrics.keys() and all(metrics[name] is not None for name in required), "Required recovery metrics available")
        holdout_ids = [item["id"] for item in cases if item.get("experiment_group") == "HOLDOUT"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            intervention_sets = list(pool.map(
                lambda case_id: requests.get(f"{base}/cases/{case_id}/interventions", timeout=30).json(),
                holdout_ids,
            ))
        check(all(not items for items in intervention_sets), "Holdout has no interventions")
        check(bool(health_data.json().get("methods")), "Payment Health response available")
        print(f"\nRecoverIQ smoke test passed. Batch: {batch_id}")
        return 0
    except (requests.RequestException, ValueError, KeyError, AssertionError) as exc:
        print(f"\nRecoverIQ smoke test failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
