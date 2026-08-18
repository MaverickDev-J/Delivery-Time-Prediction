import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import joblib
import pandas as pd
from sklearn import set_config
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder, OrdinalEncoder

from contracts.features import (
    DISTANCE_TYPE_ORDER,
    NOMINAL_FEATURES,
    NUMERICAL_FEATURES,
    ORDINAL_FEATURES,
    TARGET_COLUMN,
    TRAFFIC_ORDER,
)

# Output pandas dataframes from transformers
set_config(transform_output="pandas")

logger = logging.getLogger("data_preprocessing")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)


def build_preprocessor() -> ColumnTransformer:
    """Build the single source-of-truth ColumnTransformer pipeline."""
    return ColumnTransformer(
        transformers=[
            (
                "scale",
                MinMaxScaler(),
                NUMERICAL_FEATURES,
            ),
            (
                "nominal_encode",
                OneHotEncoder(
                    drop="first",
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
                NOMINAL_FEATURES,
            ),
            (
                "ordinal_encode",
                OrdinalEncoder(
                    categories=[TRAFFIC_ORDER, DISTANCE_TYPE_ORDER],
                    encoded_missing_value=-999,
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                ),
                ORDINAL_FEATURES,
            ),
        ],
        remainder="drop",
        n_jobs=-1,
        verbose_feature_names_out=False,
    )


def load_data(data_path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(data_path)
        return df
    except FileNotFoundError:
        logger.error(f"The file to load does not exist: {data_path}")
        raise


def make_X_and_y(data: pd.DataFrame, target_column: str):
    X = data.drop(columns=[target_column], errors="ignore")
    y = data[target_column] if target_column in data.columns else None
    return X, y


def join_X_and_y(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    return X.join(y, how="inner")


if __name__ == "__main__":
    train_data_path = root_path / "data" / "interim" / "train.csv"
    test_data_path = root_path / "data" / "interim" / "test.csv"
    save_data_dir = root_path / "data" / "processed"
    save_data_dir.mkdir(exist_ok=True, parents=True)

    save_train_trans_path = save_data_dir / "train_trans.csv"
    save_test_trans_path = save_data_dir / "test_trans.csv"

    preprocessor = build_preprocessor()

    train_df = load_data(train_data_path).dropna()
    test_df = load_data(test_data_path).dropna()
    logger.info(f"Loaded train ({train_df.shape}) and test ({test_df.shape})")

    X_train, y_train = make_X_and_y(train_df, TARGET_COLUMN)
    X_test, y_test = make_X_and_y(test_df, TARGET_COLUMN)

    # Fit preprocessor on X_train only
    logger.info("Fitting ColumnTransformer on X_train...")
    preprocessor.fit(X_train)

    X_train_trans = preprocessor.transform(X_train)
    X_test_trans = preprocessor.transform(X_test)

    train_trans_df = join_X_and_y(X_train_trans, y_train)
    test_trans_df = join_X_and_y(X_test_trans, y_test)

    train_trans_df.to_csv(save_train_trans_path, index=False)
    test_trans_df.to_csv(save_test_trans_path, index=False)
    logger.info("Transformed datasets saved to data/processed")

    # Save preprocessor artifact
    model_save_dir = root_path / "models"
    model_save_dir.mkdir(exist_ok=True, parents=True)
    transformer_path = model_save_dir / "preprocessor.joblib"
    joblib.dump(preprocessor, transformer_path)
    logger.info(f"Preprocessor saved to {transformer_path}")
