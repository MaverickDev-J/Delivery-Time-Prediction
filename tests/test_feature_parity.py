from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from contracts.features import (
    NOMINAL_FEATURES,
    NUMERICAL_FEATURES,
    ORDINAL_FEATURES,
)
from scripts.data_clean_utils import normalise_for_inference


def test_feature_parity():
    """
    Verify that serving-time normalization + preprocessor transformation
    matches the expected input schema and produces a valid numeric vector.
    """
    root_path = Path(__file__).parent.parent
    preprocessor_path = root_path / "models" / "preprocessor.joblib"
    assert preprocessor_path.exists(), "Preprocessor artifact must exist"

    preprocessor = joblib.load(preprocessor_path)

    sample_raw = pd.DataFrame([{
        "id": "PARITY-001",
        "rider_id": "MYSRES01DEL02",
        "age": 30.0,
        "ratings": 4.7,
        "restaurant_latitude": 12.3051,
        "restaurant_longitude": 76.6554,
        "delivery_latitude": 12.3251,
        "delivery_longitude": 76.6754,
        "order_date": "20-03-2026",
        "order_time": "20:15:00",
        "weather": "windy",
        "traffic": "high",
        "vehicle_condition": 1,
        "type_of_order": "snack",
        "type_of_vehicle": "scooter",
        "festival": "no",
        "city_type": "urban",
    }])

    # Transform via inference normalizer
    norm_df = normalise_for_inference(sample_raw)

    expected_cols = set(NUMERICAL_FEATURES + NOMINAL_FEATURES + ORDINAL_FEATURES)
    assert set(norm_df.columns) == expected_cols

    # Transform through ColumnTransformer
    transformed_features = preprocessor.transform(norm_df)
    assert transformed_features is not None
    assert transformed_features.shape[0] == 1
    
    # Check for NaNs whether output is DataFrame or numpy ndarray
    arr = transformed_features.values if hasattr(transformed_features, "values") else np.asarray(transformed_features)
    assert not np.isnan(arr).any(), "Transformed feature vector contains NaNs"
