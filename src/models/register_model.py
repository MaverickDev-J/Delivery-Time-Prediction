import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import mlflow
from mlflow import MlflowClient

logger = logging.getLogger("register_model")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)


def setup_mlflow(root_path: Path):
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    repo_owner = os.getenv("DAGSHUB_REPO_OWNER")
    repo_name = os.getenv("DAGSHUB_REPO_NAME", "Delivery-Time-Prediction")

    if repo_owner and os.getenv("DAGSHUB_TOKEN"):
        try:
            import dagshub
            dagshub.init(repo_owner=repo_owner, repo_name=repo_name, mlflow=True)
        except Exception as e:
            logger.warning(f"Could not initialize DagsHub ({e})")

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    else:
        local_mlflow_dir = root_path / "mlruns"
        mlflow.set_tracking_uri(f"file:///{local_mlflow_dir.as_posix()}")


if __name__ == "__main__":
    run_info_path = root_path / "run_information.json"
    reports_dir = root_path / "reports"
    reports_dir.mkdir(exist_ok=True, parents=True)
    registry_report_path = reports_dir / "registry.json"

    setup_mlflow(root_path)

    with open(run_info_path, "r") as f:
        run_info = json.load(f)

    model_name = run_info["model_name"]
    model_uri = run_info["artifact_path"]

    logger.info(f"Registering model '{model_name}' from URI: {model_uri}")
    registered_model = mlflow.register_model(
        model_uri=model_uri,
        name=model_name,
    )

    version = str(registered_model.version)
    logger.info(f"Registered model version: {version}")

    client = MlflowClient()

    # In MLflow 3.x, use model aliases instead of deprecated stages
    # Set alias @champion for active production model version
    try:
        client.set_registered_model_alias(
            name=model_name,
            alias="champion",
            version=version,
        )
        logger.info(f"Assigned alias '@champion' to version {version}")
    except Exception as e:
        logger.warning(f"Alias assignment notice: {e}")

    registry_data = {
        "model_name": model_name,
        "version": version,
        "alias": "champion",
        "registered_uri": model_uri,
        "status": "READY",
    }

    with open(registry_report_path, "w") as f:
        json.dump(registry_data, f, indent=4)

    logger.info(f"Registry report written to {registry_report_path}")