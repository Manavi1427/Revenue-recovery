from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_PATH = DATA_DIR / "raw" / "synthetic_payments.csv"
PROCESSED_DATA_PATH = DATA_DIR / "processed" / "recovery_training_data.csv"
MODEL_PATH = DATA_DIR / "models" / "recovery_pipeline.joblib"
METRICS_PATH = DATA_DIR / "metrics" / "recovery_model_metrics.json"
