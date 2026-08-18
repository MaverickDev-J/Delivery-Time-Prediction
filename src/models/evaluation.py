import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import joblib
import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score

from contracts.features import TARGET_COLUMN

logger = logging.getLogger("model_evaluation")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)


def setup_mlflow(root_path: Path):
    """Configure MLflow tracking server from environment variables or local directory fallback."""
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    repo_owner = os.getenv("DAGSHUB_REPO_OWNER")
    repo_name = os.getenv("DAGSHUB_REPO_NAME", "Delivery-Time-Prediction")

    if repo_owner and os.getenv("DAGSHUB_TOKEN"):
        try:
            import dagshub
            dagshub.init(repo_owner=repo_owner, repo_name=repo_name, mlflow=True)
            logger.info(f"Initialized DagsHub tracking for {repo_owner}/{repo_name}")
        except Exception as e:
            logger.warning(f"Could not initialize DagsHub ({e}), using local MLflow tracking.")

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    else:
        local_mlflow_dir = root_path / "mlruns"
        local_mlflow_dir.mkdir(exist_ok=True, parents=True)
        mlflow.set_tracking_uri(f"file:///{local_mlflow_dir.as_posix()}")

    mlflow.set_experiment("DeliverIQ_Pipeline")


def calculate_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict:
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred))
    # Business metric: percentage of deliveries > 5 mins later than predicted
    late_rate = float(np.mean((y_true.values - y_pred) > 5.0))
    # Business metric: percentage of deliveries > 5 mins earlier than predicted
    early_rate = float(np.mean((y_pred - y_true.values) > 5.0))

    return {
        "mae": mae,
        "r2": r2,
        "late_rate_gt_5min": late_rate,
        "early_rate_gt_5min": early_rate,
    }


if __name__ == "__main__":
    train_data_path = root_path / "data" / "processed" / "train_trans.csv"
    test_data_path = root_path / "data" / "processed" / "test_trans.csv"
    model_path = root_path / "models" / "model.joblib"

    setup_mlflow(root_path)

    train_data = pd.read_csv(train_data_path)
    test_data = pd.read_csv(test_data_path)

    X_train = train_data.drop(columns=[TARGET_COLUMN])
    y_train = train_data[TARGET_COLUMN]

    X_test = test_data.drop(columns=[TARGET_COLUMN])
    y_test = test_data[TARGET_COLUMN]

    logger.info("Loading trained model...")
    model = joblib.load(model_path)

    logger.info("Evaluating predictions on train and test subsets...")
    y_train_pred = model.predict(X_train)
    y_test_pred = model.predict(X_test)

    train_metrics = calculate_metrics(y_train, y_train_pred)
    test_metrics = calculate_metrics(y_test, y_test_pred)

    logger.info(f"Test MAE: {test_metrics['mae']:.2f} min | Test R2: {test_metrics['r2']:.3f} | Late Rate: {test_metrics['late_rate_gt_5min'] * 100:.1f}%")

    with mlflow.start_run() as run:
        mlflow.set_tag("pipeline", "deliveriq_dvc")
        mlflow.set_tag("model_type", "stacking_regressor")

        for k, v in train_metrics.items():
            mlflow.log_metric(f"train_{k}", v)
        for k, v in test_metrics.items():
            mlflow.log_metric(f"test_{k}", v)

        # Log artifacts
        preprocessor_path = root_path / "models" / "preprocessor.joblib"
        if preprocessor_path.exists():
            mlflow.log_artifact(preprocessor_path)

        signature = mlflow.models.infer_signature(
            model_input=X_train.sample(10, random_state=42),
            model_output=model.predict(X_train.sample(10, random_state=42))
        )
        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="delivery_eta_model",
            signature=signature
        )

        artifact_uri = mlflow.get_artifact_uri("delivery_eta_model")
        run_id = run.info.run_id

    # Save run information for registration
    run_info = {
        "run_id": run_id,
        "artifact_path": artifact_uri,
        "model_name": "delivery_time_pred_model",
        "metrics": test_metrics,
    }

    run_info_file = root_path / "run_information.json"
    with open(run_info_file, "w") as f:
        json.dump(run_info, f, indent=4)

    logger.info(f"Saved run evaluation metadata to {run_info_file}")