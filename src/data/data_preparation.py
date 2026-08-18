import logging
from pathlib import Path

import pandas as pd
import yaml
from sklearn.model_selection import train_test_split

TARGET = "time_taken"

logger = logging.getLogger("data_preparation")
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


def split_data(
    data: pd.DataFrame,
    test_size: float = 0.25,
    random_state: int = 42,
    strategy: str = "random"
):
    if strategy == "time" and "order_date" in data.columns:
        # Sort chronologically if order_date column exists
        sorted_data = data.sort_values(by="order_date")
        split_idx = int(len(sorted_data) * (1 - test_size))
        train_data = sorted_data.iloc[:split_idx]
        test_data = sorted_data.iloc[split_idx:]
    else:
        train_data, test_data = train_test_split(
            data,
            test_size=test_size,
            random_state=random_state
        )
    return train_data, test_data


def read_params(file_path: Path) -> dict:
    with open(file_path, "r") as f:
        return yaml.safe_load(f)


if __name__ == "__main__":
    root_path = Path(__file__).parent.parent.parent
    data_path = root_path / "data" / "cleaned" / "swiggy_cleaned.csv"
    save_data_dir = root_path / "data" / "interim"
    save_data_dir.mkdir(exist_ok=True, parents=True)

    save_train_path = save_data_dir / "train.csv"
    save_test_path = save_data_dir / "test.csv"
    params_file_path = root_path / "params.yaml"

    df = load_data(data_path)
    logger.info("Cleaned data loaded successfully")

    parameters = read_params(params_file_path).get("Data_Preparation", {})
    test_size = parameters.get("test_size", 0.25)
    random_state = parameters.get("random_state", 42)
    strategy = parameters.get("strategy", "random")

    train_data, test_data = split_data(
        df,
        test_size=test_size,
        random_state=random_state,
        strategy=strategy
    )
    logger.info(f"Dataset split: train={train_data.shape}, test={test_data.shape}")

    train_data.to_csv(save_train_path, index=False)
    test_data.to_csv(save_test_path, index=False)
    logger.info("Train and test datasets saved to data/interim")
