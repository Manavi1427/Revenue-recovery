import json

import joblib

from ml.features import MODEL_FEATURES, TARGET_COLUMN
from ml.generate_data import generate_synthetic_data
from ml.predictor import predict_probability, reset_model_cache
from ml.train import train_model


def test_synthetic_data_contract_and_reproducibility():
    first = generate_synthetic_data(200, seed=7)
    second = generate_synthetic_data(200, seed=7)
    assert set(MODEL_FEATURES + [TARGET_COLUMN]).issubset(first.columns)
    assert set(first[TARGET_COLUMN]) == {0, 1}
    assert first.equals(second)


def test_training_artifacts_and_predictor_support_unseen_values(tmp_path):
    data_path = tmp_path / "training.csv"
    model_path = tmp_path / "model.joblib"
    metrics_path = tmp_path / "metrics.json"
    generate_synthetic_data(500, seed=42).to_csv(data_path, index=False)
    metrics = train_model(data_path, model_path, metrics_path)

    pipeline = joblib.load(model_path)
    assert set(pipeline.named_steps) == {"preprocessing", "classifier"}
    saved = json.loads(metrics_path.read_text())
    assert saved["dataset_type"] == "synthetic"
    assert 0 <= saved["roc_auc"] <= 1
    assert metrics["test_rows"] > 0

    reset_model_cache()
    row = {name: 0 for name in MODEL_FEATURES}
    row.update(payment_method="brand_new_method", error_source="new_source", error_step="new_step", error_reason="new_reason")
    probability, version = predict_probability(row, model_path)
    assert 0 <= probability <= 1
    assert version == "logistic-regression-synthetic-v1"
