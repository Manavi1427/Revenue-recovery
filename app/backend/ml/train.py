from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES, TARGET_COLUMN
from project_paths import METRICS_PATH, MODEL_PATH, PROCESSED_DATA_PATH, RAW_DATA_PATH


MODEL_VERSION = "logistic-regression-synthetic-v1"


def train_model(data_path: Path | None = None, model_path: Path = MODEL_PATH, metrics_path: Path = METRICS_PATH) -> dict[str, Any]:
    """Fit and save the complete preprocessing and logistic-regression pipeline."""

    source = data_path or (PROCESSED_DATA_PATH if PROCESSED_DATA_PATH.exists() else RAW_DATA_PATH)
    frame = pd.read_csv(source)
    required = set(MODEL_FEATURES + [TARGET_COLUMN])
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Training data is missing columns: {sorted(missing)}")
    x_train, x_test, y_train, y_test = train_test_split(
        frame[MODEL_FEATURES], frame[TARGET_COLUMN], test_size=0.2, random_state=42,
        stratify=frame[TARGET_COLUMN],
    )
    preprocessing = ColumnTransformer([
        ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    pipeline = Pipeline([("preprocessing", preprocessing), ("classifier", LogisticRegression(max_iter=1000, random_state=42))])
    pipeline.fit(x_train, y_train)
    pipeline.model_version_ = MODEL_VERSION
    pipeline.dataset_type_ = "synthetic"
    predictions = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "confusion_matrix": confusion_matrix(y_test, predictions).astype(int).tolist(),
        "train_rows": int(len(x_train)), "test_rows": int(len(x_test)),
        "positive_rate": float(frame[TARGET_COLUMN].mean()),
        "model_type": "LogisticRegression", "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(), "dataset_type": "synthetic",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    result = train_model()
    print(json.dumps(result, indent=2))
    print(f"Model: {MODEL_PATH}")
    print(f"Metrics: {METRICS_PATH}")
