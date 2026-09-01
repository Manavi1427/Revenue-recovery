from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.features import MODEL_FEATURES
from project_paths import METRICS_PATH, MODEL_PATH


logger = logging.getLogger(__name__)
_cached_model: Any | None = None
_cached_path: Path | None = None


class ModelUnavailableError(RuntimeError):
    """Raised when the optional model cannot provide a safe prediction."""


def reset_model_cache() -> None:
    """Clear the lazy cache, mainly for retraining and tests."""

    global _cached_model, _cached_path
    _cached_model = None
    _cached_path = None


def _load_model(model_path: Path = MODEL_PATH) -> Any:
    global _cached_model, _cached_path
    resolved = model_path.resolve()
    if _cached_model is not None and _cached_path == resolved:
        return _cached_model
    if not model_path.is_file():
        raise ModelUnavailableError("Optional recovery model is not installed")
    try:
        model = joblib.load(model_path)
    except Exception as exc:
        logger.warning("Optional recovery model could not be loaded: %s", type(exc).__name__)
        raise ModelUnavailableError("Optional recovery model could not be loaded") from exc
    _cached_model, _cached_path = model, resolved
    return model


def predict_probability(row: dict[str, Any], model_path: Path = MODEL_PATH) -> tuple[float, str | None]:
    """Return a bounded positive-class probability and model version."""

    try:
        model = _load_model(model_path)
        probability = float(model.predict_proba(pd.DataFrame([{key: row.get(key) for key in MODEL_FEATURES}]))[0][1])
        if probability != probability:  # NaN is not equal to itself.
            raise ValueError("Prediction was NaN")
        return max(0.0, min(probability, 1.0)), getattr(model, "model_version_", None)
    except ModelUnavailableError:
        raise
    except Exception as exc:
        logger.warning("Optional recovery prediction failed: %s", type(exc).__name__)
        raise ModelUnavailableError("Optional recovery prediction failed") from exc


def get_model_status(model_path: Path = MODEL_PATH, metrics_path: Path = METRICS_PATH) -> dict[str, Any]:
    """Describe optional artifact availability without exposing local paths or errors."""

    status: dict[str, Any] = {"model_available": False, "fallback_available": True, "metrics_available": metrics_path.is_file()}
    try:
        model = _load_model(model_path)
        status.update(model_available=True, model_type=type(model.named_steps.get("classifier")).__name__, model_version=getattr(model, "model_version_", None), dataset_type=getattr(model, "dataset_type_", "synthetic"))
    except ModelUnavailableError:
        pass
    if metrics_path.is_file():
        try:
            metadata = json.loads(metrics_path.read_text(encoding="utf-8"))
            status.setdefault("model_version", metadata.get("model_version"))
            status.setdefault("dataset_type", metadata.get("dataset_type"))
        except (OSError, json.JSONDecodeError):
            status["metrics_available"] = False
    return status
