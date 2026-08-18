import time
from contextlib import asynccontextmanager

import joblib
import pandas as pd
import uvicorn
from sklearn.pipeline import Pipeline

from contracts.features import (
    FEATURE_SCHEMA_VERSION,
    OrderPredictionRequest,
    OrderPredictionResponse,
)
from core.app_factory import create_app
from core.config import ETAServiceSettings
from core.errors import ModelNotReadyException
from core.logging import get_correlation_id, setup_logger
from scripts.data_clean_utils import normalise_for_inference

logger = setup_logger("eta-service", service_name="eta-service")
settings = ETAServiceSettings()

# In-memory artifact state
model_state = {
    "model_pipeline": None,
    "model_version": "1.0.0",
    "ready": False,
    "degraded_fallback_eta": 32.0,  # Historical median fallback
}


def load_local_pipeline(settings: ETAServiceSettings) -> Pipeline | None:
    """Load preprocessor and model from local disk artifacts."""
    try:
        preprocessor = joblib.load(settings.preprocessor_artifact_path)
        model = joblib.load(settings.model_artifact_path)
        pipe = Pipeline(steps=[
            ("preprocess", preprocessor),
            ("regressor", model),
        ])
        logger.info("Successfully loaded local model pipeline artifacts.")
        return pipe
    except Exception as e:
        logger.error(f"Failed to load local model artifacts: {e}")
        return None


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: load model artifacts at startup."""
    logger.info("Starting up DeliverIQ ETA Prediction Service...")
    pipe = load_local_pipeline(settings)
    if pipe:
        model_state["model_pipeline"] = pipe
        model_state["ready"] = True
    else:
        logger.warning("Service starting in degraded fallback mode (artifacts missing).")
        model_state["ready"] = False

    yield

    logger.info("Shutting down ETA Prediction Service.")


app = create_app(settings=settings, lifespan=lifespan)


@app.get("/ready", tags=["Health"])
async def ready():
    """Readiness probe verifying model pipeline availability."""
    if not model_state["ready"] and model_state["model_pipeline"] is None:
        raise ModelNotReadyException(detail="Model artifacts are not loaded.")
    return {
        "status": "READY",
        "service": settings.service_name,
        "model_version": model_state["model_version"],
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }


@app.get("/version", tags=["Metadata"])
async def version():
    """Service metadata and version info."""
    return {
        "service": settings.service_name,
        "model_version": model_state["model_version"],
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "degraded_mode": not model_state["ready"],
    }


@app.post("/predict", response_model=OrderPredictionResponse, tags=["Inference"])
async def predict(request: OrderPredictionRequest):
    """
    Generate an at-cart ETA prediction with confidence intervals.
    Degrades to historical median heuristic if model is unavailable.
    """
    start_time = time.perf_counter()
    correlation_id = get_correlation_id()

    # Convert Pydantic request to DataFrame
    req_dict = request.model_dump()
    raw_df = pd.DataFrame([req_dict])

    # Normalise features for inference without dropping rows
    normalized_df = normalise_for_inference(raw_df)

    is_degraded = False
    eta_prediction: float

    if model_state["ready"] and model_state["model_pipeline"] is not None:
        try:
            preds = model_state["model_pipeline"].predict(normalized_df)
            eta_prediction = float(preds[0])
        except Exception as e:
            logger.error(f"Inference execution failed: {e}. Falling back to degraded mode.")
            is_degraded = True
            eta_prediction = model_state["degraded_fallback_eta"]
    else:
        is_degraded = True
        eta_prediction = model_state["degraded_fallback_eta"]

    # Compute prediction intervals
    margin = settings.prediction_interval_margin
    lower_bound = max(5.0, round(eta_prediction - margin, 1))
    upper_bound = max(lower_bound + 2.0, round(eta_prediction + margin, 1))
    point_estimate = round(eta_prediction, 1)

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    logger.info(
        f"ETA prediction: {point_estimate} min [{lower_bound}-{upper_bound}] | "
        f"Latency: {latency_ms}ms | Degraded: {is_degraded}"
    )

    return OrderPredictionResponse(
        eta_minutes=point_estimate,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        model_version=model_state["model_version"],
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        degraded=is_degraded,
        latency_ms=latency_ms,
        request_id=correlation_id,
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host=settings.host, port=settings.port, reload=settings.debug)