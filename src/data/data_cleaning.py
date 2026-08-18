import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import pandas as pd

from scripts.data_clean_utils import perform_data_cleaning

logger = logging.getLogger("data_cleaning")
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


if __name__ == "__main__":
    cleaned_data_save_dir = root_path / "data" / "cleaned"
    cleaned_data_save_dir.mkdir(exist_ok=True, parents=True)

    cleaned_data_filename = "swiggy_cleaned.csv"
    cleaned_data_save_path = cleaned_data_save_dir / cleaned_data_filename
    data_load_path = root_path / "data" / "raw" / "swiggy.csv"

    logger.info("Loading raw Swiggy data...")
    df = load_data(data_load_path)

    logger.info("Performing data cleaning and at-cart feature extraction...")
    cleaned_df = perform_data_cleaning(df)

    cleaned_df.to_csv(cleaned_data_save_path, index=False)
    logger.info(f"Cleaned dataset with shape {cleaned_df.shape} saved to {cleaned_data_save_path}")