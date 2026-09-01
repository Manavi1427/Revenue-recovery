import json

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier

from ml.features import MODEL_FEATURES, TARGET_COLUMN
from ml.forest_models import DecisionForestClassifier
from ml.generate_data import generate_synthetic_data
from ml.predictor import predict_probability, reset_model_cache
from ml.train import build_candidate_models, choose_best_model, train_model


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
    candidates = {
        "logistic_regression": LogisticRegression(max_iter=500, random_state=42),
        "decision_tree": DecisionTreeClassifier(max_depth=4, random_state=42),
    }
    metrics = train_model(
        data_path, model_path, metrics_path,
        candidate_models=candidates, cross_validation_folds=3,
    )

    pipeline = joblib.load(model_path)
    assert set(pipeline.named_steps) == {"preprocessing", "classifier"}
    saved = json.loads(metrics_path.read_text())
    assert saved["dataset_type"] == "synthetic"
    assert 0 <= saved["roc_auc"] <= 1
    assert saved["selected_model"] in candidates
    assert saved["selection_metric"] == "cross_validated_roc_auc"
    assert set(saved["model_comparison"]) == set(candidates)
    assert saved["cross_validation_folds"] == 3
    assert saved["test_metrics"]["brier_score"] >= 0
    assert metrics["test_rows"] > 0

    reset_model_cache()
    row = {name: 0 for name in MODEL_FEATURES}
    row.update(payment_method="brand_new_method", error_source="new_source", error_step="new_step", error_reason="new_reason")
    probability, version = predict_probability(row, model_path)
    assert 0 <= probability <= 1
    assert version == saved["model_version"]


def test_default_comparison_contains_requested_models():
    assert set(build_candidate_models()) == {
        "logistic_regression", "decision_tree", "random_forest", "extra_trees", "svm",
    }


def test_selection_uses_roc_auc_and_simple_model_tie_break():
    comparison = {
        "logistic_regression": {"roc_auc": {"mean": 0.74, "std": 0.01}},
        "random_forest": {"roc_auc": {"mean": 0.749, "std": 0.02}},
        "decision_tree": {"roc_auc": {"mean": 0.68, "std": 0.03}},
    }
    assert choose_best_model(comparison) == "logistic_regression"

    comparison["random_forest"]["roc_auc"]["mean"] = 0.76
    assert choose_best_model(comparison) == "random_forest"


def test_forest_prototype_returns_bounded_probabilities():
    frame = generate_synthetic_data(100, seed=9)
    model = DecisionForestClassifier(n_estimators=5, max_depth=4, min_samples_leaf=2)
    model.fit(frame[["amount", "previous_attempts"]].to_numpy(), frame[TARGET_COLUMN])
    probabilities = model.predict_proba(frame[["amount", "previous_attempts"]].to_numpy()[:3])
    assert probabilities.shape == (3, 2)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    assert (abs(probabilities.sum(axis=1) - 1) < 1e-9).all()
