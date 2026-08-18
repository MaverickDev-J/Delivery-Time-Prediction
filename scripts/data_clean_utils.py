import numpy as np
import pandas as pd

from contracts.features import (
    NOMINAL_FEATURES,
    NUMERICAL_FEATURES,
    ORDINAL_FEATURES,
    TARGET_COLUMN,
)

# Raw columns to drop during feature engineering pipeline
COLUMNS_TO_DROP = [
    "id",
    "rider_id",
    "restaurant_latitude",
    "restaurant_longitude",
    "delivery_latitude",
    "delivery_longitude",
    "order_date",
    "order_time",
    "order_time_hour",
    "order_day",
    "city_name",
    "order_day_of_week",
    "order_month",
    "pickup_time_minutes",  # Explicitly dropped (Leakage fix)
    "multiple_deliveries",  # Explicitly dropped (Leakage fix)
]


def change_column_names(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw dataset column names to lower_snake_case."""
    rename_dict = {
        "delivery_person_id": "rider_id",
        "delivery_person_age": "age",
        "delivery_person_ratings": "ratings",
        "delivery_location_latitude": "delivery_latitude",
        "delivery_location_longitude": "delivery_longitude",
        "time_orderd": "order_time",
        "time_order_picked": "order_picked_time",
        "weatherconditions": "weather",
        "road_traffic_density": "traffic",
        "city": "city_type",
        "time_taken(min)": TARGET_COLUMN,
    }
    return (
        data.rename(str.lower, axis=1)
        .rename(rename_dict, axis=1)
    )


def time_of_day(ser: pd.Series) -> pd.Series:
    """Classify hour of day into standard operational windows."""
    return pd.cut(
        ser,
        bins=[-1, 6, 12, 17, 20, 24],
        right=True,
        labels=["after_midnight", "morning", "afternoon", "evening", "night"],
    )


def calculate_haversine_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Haversine distance in kilometers from restaurant and delivery coordinates."""
    lat1 = df["restaurant_latitude"].abs()
    lon1 = df["restaurant_longitude"].abs()
    lat2 = df["delivery_latitude"].abs()
    lon2 = df["delivery_longitude"].abs()

    lon1_rad, lat1_rad, lon2_rad, lat2_rad = map(np.radians, [lon1, lon2, lat1, lat2])

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.clip(np.sqrt(a), 0, 1.0))
    distance_km = 6371.0 * c

    return df.assign(distance=distance_km)


def create_distance_type(data: pd.DataFrame) -> pd.DataFrame:
    """Bin continuous distance into ordinal classification bands."""
    return data.assign(
        distance_type=pd.cut(
            data["distance"],
            bins=[-0.1, 5, 10, 15, 1000],
            right=False,
            labels=["short", "medium", "long", "very_long"],
        )
    )


def filter_training_rows(data: pd.DataFrame) -> pd.DataFrame:
    """
    Offline training data cleaning.
    Explicitly filters anomalies: minor riders (age < 18), invalid ratings (ratings > 5 or 6-star anomalies).
    """
    cleaned = data.copy()
    
    # Cast and filter age
    if "age" in cleaned.columns:
        cleaned["age"] = pd.to_numeric(cleaned["age"], errors="coerce")
        cleaned = cleaned[cleaned["age"] >= 18.0]

    # Cast and filter ratings
    if "ratings" in cleaned.columns:
        cleaned["ratings"] = pd.to_numeric(cleaned["ratings"], errors="coerce")
        cleaned = cleaned[(cleaned["ratings"] >= 1.0) & (cleaned["ratings"] <= 5.0)]

    # Clean target column if present
    if TARGET_COLUMN in cleaned.columns:
        if cleaned[TARGET_COLUMN].dtype == object:
            cleaned[TARGET_COLUMN] = (
                cleaned[TARGET_COLUMN]
                .astype(str)
                .str.replace("(min) ", "", regex=False)
                .str.strip()
            )
        cleaned[TARGET_COLUMN] = pd.to_numeric(cleaned[TARGET_COLUMN], errors="coerce")

    # Drop NaNs for training
    return cleaned.dropna()


def extract_features(data: pd.DataFrame) -> pd.DataFrame:
    """Core feature engineering transformation common to both training and inference."""
    df = data.copy()

    # Datetime handling
    if "order_date" in df.columns:
        order_date_dt = pd.to_datetime(df["order_date"], dayfirst=True, errors="coerce")
        df["is_weekend"] = order_date_dt.dt.day_name().isin(["Saturday", "Sunday"]).astype(int)
    else:
        df["is_weekend"] = 0

    if "order_time" in df.columns:
        # Handle time parsing safely
        order_time_dt = pd.to_datetime(df["order_time"], format="mixed", errors="coerce")
        df["order_time_hour"] = order_time_dt.dt.hour.fillna(12).astype(int)
        df["order_time_of_day"] = time_of_day(df["order_time_hour"])
    else:
        df["order_time_of_day"] = "evening"

    # Categorical standardizations
    for col in ["weather", "traffic", "type_of_order", "type_of_vehicle", "festival", "city_type"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace("conditions ", "", regex=False)
                .str.strip()
                .str.lower()
                .replace("nan", np.nan)
            )

    # Calculate distance and distance bins
    df = calculate_haversine_distance(df)
    df = create_distance_type(df)

    return df


def normalise_for_inference(data: pd.DataFrame) -> pd.DataFrame:
    """
    Serving-time normalization.
    Guarantees no row dropping. Extracts features and returns valid DataFrame for preprocessor.
    """
    df = change_column_names(data)
    df = extract_features(df)

    # Select only required feature columns
    all_feature_cols = NUMERICAL_FEATURES + NOMINAL_FEATURES + ORDINAL_FEATURES
    existing_cols = [c for c in all_feature_cols if c in df.columns]
    
    return df[existing_cols]


def perform_data_cleaning(data: pd.DataFrame) -> pd.DataFrame:
    """
    Full pipeline data preparation for training / interim data.
    """
    df = change_column_names(data)
    df = filter_training_rows(df)
    df = extract_features(df)

    # Columns to drop from training dataset
    cols_to_drop = [c for c in COLUMNS_TO_DROP if c in df.columns]
    df = df.drop(columns=cols_to_drop, errors="ignore")

    return df.dropna()
