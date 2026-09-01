from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, brier_score_loss, confusion_matrix,
    f1_score, log_loss, make_scorer, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from ml.features import CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES, TARGET_COLUMN
from ml.forest_models import DecisionForestClassifier
from project_paths import METRICS_PATH, MODEL_PATH, PROCESSED_DATA_PATH, RAW_DATA_PATH


RANDOM_SEED = 42
MODEL_VERSION_PREFIX = "recovery-synthetic-v2"
SELECTION_METRIC = "cross_validated_roc_auc"
ROC_AUC_TIE_MARGIN = 0.01
MODEL_PREFERENCE = ["logistic_regression", "random_forest", "extra_trees", "svm", "decision_tree"]


def build_candidate_models() -> dict[str, BaseEstimator]:
    """Return bounded, probability-capable classifiers for comparison."""

    return {
        "logistic_regression": LogisticRegression(max_iter=1000, class_weight="balanced", random_state=RANDOM_SEED),
        "decision_tree": DecisionTreeClassifier(max_depth=8, min_samples_leaf=20, class_weight="balanced", random_state=RANDOM_SEED),
        "random_forest": DecisionForestClassifier(
            n_estimators=200, max_depth=12, min_samples_leaf=10,
            class_weight="balanced", bootstrap=True, splitter="best", random_state=RANDOM_SEED,
        ),
        "extra_trees": DecisionForestClassifier(
            n_estimators=200, max_depth=12, min_samples_leaf=10,
            class_weight="balanced", bootstrap=False, splitter="random", random_state=RANDOM_SEED,
        ),
        "svm": CalibratedClassifierCV(
            SVC(C=1.0, kernel="rbf", class_weight="balanced", random_state=RANDOM_SEED),
            cv=3, ensemble=False,
        ),
    }


def build_preprocessing() -> ColumnTransformer:
    """Build fresh preprocessing shared by every classifier."""

    return ColumnTransformer([
        ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])


def build_pipeline(classifier: BaseEstimator) -> Pipeline:
    """Keep preprocessing and the classifier together for safe inference."""

    return Pipeline([("preprocessing", build_preprocessing()), ("classifier", classifier)])


def compare_models(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    candidate_models: dict[str, BaseEstimator] | None = None,
    folds: int = 5,
) -> dict[str, dict[str, dict[str, float]]]:
    """Compare candidates using the same reproducible stratified folds."""

    candidates = candidate_models or build_candidate_models()
    cross_validation = StratifiedKFold(n_splits=folds, shuffle=True, random_state=RANDOM_SEED)
    scoring = {
        "roc_auc": "roc_auc", "accuracy": "accuracy", "balanced_accuracy": "balanced_accuracy",
        "precision": make_scorer(precision_score, zero_division=0),
        "recall": make_scorer(recall_score, zero_division=0),
        "f1": make_scorer(f1_score, zero_division=0),
    }
    comparison: dict[str, dict[str, dict[str, float]]] = {}
    for name, classifier in candidates.items():
        scores = cross_validate(
            build_pipeline(classifier), x_train, y_train,
            cv=cross_validation, scoring=scoring, n_jobs=1,
        )
        comparison[name] = {
            metric: {"mean": float(scores[f"test_{metric}"].mean()), "std": float(scores[f"test_{metric}"].std())}
            for metric in scoring
        }
    return comparison


def choose_best_model(comparison: dict[str, dict[str, dict[str, float]]]) -> str:
    """Choose by ROC-AUC, preferring simplicity for effectively tied models."""

    if not comparison:
        raise ValueError("At least one candidate model is required")
    best_auc = max(result["roc_auc"]["mean"] for result in comparison.values())
    tied = {name for name, result in comparison.items() if best_auc - result["roc_auc"]["mean"] <= ROC_AUC_TIE_MARGIN}
    for preferred in MODEL_PREFERENCE:
        if preferred in tied:
            return preferred
    return max(tied, key=lambda name: comparison[name]["roc_auc"]["mean"])


def train_model(
    data_path: Path | None = None,
    model_path: Path = MODEL_PATH,
    metrics_path: Path = METRICS_PATH,
    candidate_models: dict[str, BaseEstimator] | None = None,
    cross_validation_folds: int = 5,
) -> dict[str, Any]:
    """Compare candidates, evaluate the winner once, and save its pipeline."""

    source = data_path or (PROCESSED_DATA_PATH if PROCESSED_DATA_PATH.exists() else RAW_DATA_PATH)
    frame = pd.read_csv(source)
    required = set(MODEL_FEATURES + [TARGET_COLUMN])
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Training data is missing columns: {sorted(missing)}")
    x_train, x_test, y_train, y_test = train_test_split(
        frame[MODEL_FEATURES], frame[TARGET_COLUMN], test_size=0.2, random_state=RANDOM_SEED,
        stratify=frame[TARGET_COLUMN],
    )
    candidates = candidate_models or build_candidate_models()
    comparison = compare_models(x_train, y_train, candidates, cross_validation_folds)
    winner_name = choose_best_model(comparison)
    pipeline = build_pipeline(candidates[winner_name])
    pipeline.fit(x_train, y_train)
    model_version = f"{winner_name}-{MODEL_VERSION_PREFIX}"
    pipeline.model_version_ = model_version
    pipeline.dataset_type_ = "synthetic"
    pipeline.selection_metric_ = SELECTION_METRIC
    predictions = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    final_metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "log_loss": float(log_loss(y_test, probabilities)),
        "confusion_matrix": confusion_matrix(y_test, predictions).astype(int).tolist(),
    }
    metrics: dict[str, Any] = {
        **final_metrics, "test_metrics": final_metrics,
        "selected_model": winner_name, "selection_metric": SELECTION_METRIC,
        "cross_validation_folds": int(cross_validation_folds), "model_comparison": comparison,
        "train_rows": int(len(x_train)), "test_rows": int(len(x_test)),
        "positive_rate": float(frame[TARGET_COLUMN].mean()),
        "model_type": type(candidates[winner_name]).__name__, "model_version": model_version,
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
