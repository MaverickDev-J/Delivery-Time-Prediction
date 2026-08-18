import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import joblib
import pandas as pd
import yaml
from lightgbm import LGBMRegressor
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor, StackingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PowerTransformer

from contracts.features import TARGET_COLUMN

logger = logging.getLogger("model_training")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)


def load_data(data_path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(data_path)
        return df
    except FileNotFoundError:
        logger.error(f"The file to load does not exist: {data_path}")
        raise


def read_params(file_path: Path) -> dict:
    with open(file_path, "r") as f:
        return yaml.safe_load(f)


def make_X_and_y(data: pd.DataFrame, target_column: str):
    X = data.drop(columns=[target_column])
    y = data[target_column]
    return X, y


if __name__ == "__main__":
    data_path = root_path / "data" / "processed" / "train_trans.csv"
    params_file_path = root_path / "params.yaml"

    training_data = load_data(data_path)
    X_train, y_train = make_X_and_y(training_data, TARGET_COLUMN)
    logger.info(f"Loaded training data with shape {X_train.shape}")

    model_params = read_params(params_file_path).get("Train", {})
    rf_params = model_params.get("Random_Forest", {})
    lgbm_params = model_params.get("LightGBM", {})

    logger.info("Initializing base estimators: Random Forest and LightGBM...")
    rf = RandomForestRegressor(**rf_params)
    lgbm = LGBMRegressor(**lgbm_params)
    meta_model = LinearRegression()

    stacking_reg = StackingRegressor(
        estimators=[("rf_model", rf), ("lgbm_model", lgbm)],
        final_estimator=meta_model,
        cv=5,
        n_jobs=-1,
    )

    power_transform = PowerTransformer()
    model = TransformedTargetRegressor(
        regressor=stacking_reg,
        transformer=power_transform,
    )

    logger.info("Fitting Stacking Regressor pipeline on training data...")
    model.fit(X_train, y_train)
    logger.info("Model training completed successfully.")

    model_save_dir = root_path / "models"
    model_save_dir.mkdir(exist_ok=True, parents=True)

    joblib.dump(model, model_save_dir / "model.joblib")
    joblib.dump(model.regressor_, model_save_dir / "stacking_regressor.joblib")
    joblib.dump(model.transformer_, model_save_dir / "power_transformer.joblib")
    logger.info(f"Trained artifacts saved to {model_save_dir}")
