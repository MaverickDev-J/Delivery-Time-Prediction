from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import mean_absolute_error

from contracts.features import TARGET_COLUMN


def test_offline_model_performance():
    root_path = Path(__file__).parent.parent
    model_path = root_path / "models" / "model.joblib"
    test_data_path = root_path / "data" / "processed" / "test_trans.csv"

    assert model_path.exists(), "Trained model artifact must exist"
    assert test_data_path.exists(), "Processed test dataset must exist"

    model = joblib.load(model_path)
    test_df = pd.read_csv(test_data_path)

    X_test = test_df.drop(columns=[TARGET_COLUMN])
    y_test = test_df[TARGET_COLUMN]

    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)

    # Threshold for leakage-free at-cart delivery ETA prediction
    threshold_mae = 6.0
    assert mae <= threshold_mae, f"Model test MAE ({mae:.2f} min) exceeds threshold of {threshold_mae} min"