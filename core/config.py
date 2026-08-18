
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Common configuration across all DeliverIQ microservices."""
    service_name: str = Field(default="deliveriq-service", description="Name of the microservice")
    environment: str = Field(default="development", description="Runtime environment: development | test | production")
    debug: bool = Field(default=False, description="Enable debug mode")
    host: str = Field(default="0.0.0.0", description="Host address to bind HTTP server")
    port: int = Field(default=8000, description="HTTP port")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # Redis configuration for cache, idempotency, and stream messaging
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URI")
    
    # PostgreSQL configuration
    database_url: str | None = Field(default=None, description="Primary database connection URI")
    
    # MLflow tracking configuration
    mlflow_tracking_uri: str | None = Field(default=None, description="Remote or local MLflow tracking server")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class ETAServiceSettings(BaseServiceSettings):
    """Configuration specific to ETA ML serving service."""
    service_name: str = "eta-service"
    port: int = 8000
    model_artifact_path: str = Field(default="models/model.joblib", description="Local path to trained stacking regressor")
    preprocessor_artifact_path: str = Field(default="models/preprocessor.joblib", description="Local path to preprocessor")
    power_transformer_artifact_path: str = Field(default="models/power_transformer.joblib", description="Local path to power transformer")
    model_alias: str = Field(default="champion", description="MLflow registered model alias to serve")
    prediction_interval_margin: float = Field(default=4.0, description="Default interval margin around point prediction (+/- mins)")
