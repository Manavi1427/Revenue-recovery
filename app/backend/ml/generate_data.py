from __future__ import annotations

import numpy as np
import pandas as pd

from ml.features import TARGET_COLUMN
from project_paths import PROCESSED_DATA_PATH, RAW_DATA_PATH


def generate_synthetic_data(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    """Create reproducible demonstration data with overlapping target classes."""

    rng = np.random.default_rng(seed)
    methods = rng.choice(["upi", "card", "netbanking", "wallet"], rows)
    reasons = rng.choice(
        ["incorrect_pin", "insufficient_funds", "bank_unavailable", "expired_card", "payment_timed_out", "unknown"],
        rows,
    )
    source_map = {
        "incorrect_pin": "customer", "insufficient_funds": "customer",
        "bank_unavailable": "bank", "expired_card": "customer",
        "payment_timed_out": "gateway", "unknown": "unknown",
    }
    step_map = {
        "incorrect_pin": "payment_authentication", "insufficient_funds": "payment_authorization",
        "bank_unavailable": "payment_processing", "expired_card": "payment_authentication",
        "payment_timed_out": "payment_processing", "unknown": "unknown",
    }
    attempts = rng.integers(1, 6, rows)
    probability = np.full(rows, 0.50)
    probability += np.where(reasons == "incorrect_pin", 0.25, 0)
    probability += np.where(reasons == "bank_unavailable", 0.08, 0)
    probability -= np.where(reasons == "insufficient_funds", 0.12, 0)
    probability -= np.where(reasons == "expired_card", 0.22, 0)
    probability -= np.where(reasons == "unknown", 0.18, 0)
    probability += np.where(methods == "upi", 0.05, 0)
    probability -= (attempts - 1) * 0.05
    probability = np.clip(probability, 0.08, 0.92)
    frame = pd.DataFrame({
        "amount": rng.integers(1000, 500001, rows),
        "payment_method": methods,
        "error_source": [source_map[value] for value in reasons],
        "error_step": [step_map[value] for value in reasons],
        "error_reason": reasons,
        "hour_of_day": rng.integers(0, 24, rows),
        "day_of_week": rng.integers(0, 7, rows),
        "previous_attempts": attempts,
        TARGET_COLUMN: rng.binomial(1, probability),
    })
    return frame


def save_synthetic_data(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    """Generate and save raw and clean synthetic training CSV files."""

    frame = generate_synthetic_data(rows, seed)
    for path in (RAW_DATA_PATH, PROCESSED_DATA_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    return frame


if __name__ == "__main__":
    data = save_synthetic_data()
    print(f"Rows: {len(data)}")
    print(f"Class distribution: {data[TARGET_COLUMN].value_counts().sort_index().to_dict()}")
    print(f"Output: {RAW_DATA_PATH}")
