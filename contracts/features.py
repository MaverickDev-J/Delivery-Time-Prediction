from enum import Enum

from pydantic import BaseModel, Field

FEATURE_SCHEMA_VERSION = "1.0.0"

# --- Feature Column Definitions for At-Cart ETA Prediction ---
# Target leakage fix: Removed 'pickup_time_minutes' and 'multiple_deliveries' from at-cart prediction
NUMERICAL_FEATURES = ["age", "ratings", "distance"]

NOMINAL_FEATURES = [
    "weather",
    "type_of_order",
    "type_of_vehicle",
    "festival",
    "city_type",
    "is_weekend",
    "order_time_of_day",
]

ORDINAL_FEATURES = ["traffic", "distance_type"]

TARGET_COLUMN = "time_taken"

# --- Fixed Category Encodings ---
TRAFFIC_ORDER = ["low", "medium", "high", "jam"]
DISTANCE_TYPE_ORDER = ["short", "medium", "long", "very_long"]

# Categorical Enums for Strict Input Validation
class WeatherCondition(str, Enum):
    SUNNY = "sunny"
    STORMY = "stormy"
    SANDSTORMS = "sandstorms"
    WINDY = "windy"
    FOG = "fog"
    CLOUDY = "cloudy"


class TrafficDensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    JAM = "jam"


class OrderType(str, Enum):
    SNACK = "snack"
    MEAL = "meal"
    DRINKS = "drinks"
    BUFFET = "buffet"


class VehicleType(str, Enum):
    MOTORCYCLE = "motorcycle"
    SCOOTER = "scooter"
    ELECTRIC_SCOOTER = "electric_scooter"
    BICYCLE = "bicycle"


class FestivalType(str, Enum):
    YES = "yes"
    NO = "no"


class CityType(str, Enum):
    URBAN = "urban"
    METROPOLITAN = "metropolitan"
    SEMI_URBAN = "semi-urban"


class TimeOfDay(str, Enum):
    AFTER_MIDNIGHT = "after_midnight"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class OrderPredictionRequest(BaseModel):
    """Raw order prediction request schema received at checkout."""
    id: str | None = Field(default="REQ-001", description="Unique request or order ID")
    rider_id: str | None = Field(default="RIDER_DEFAULT", description="Assigned rider or default identifier")
    age: float = Field(..., ge=18.0, le=75.0, description="Rider age in years (minors excluded)")
    ratings: float = Field(..., ge=1.0, le=5.0, description="Rider rating (1.0 to 5.0 scale)")
    restaurant_latitude: float = Field(..., ge=-90.0, le=90.0, description="Restaurant latitude coordinate")
    restaurant_longitude: float = Field(..., ge=-180.0, le=180.0, description="Restaurant longitude coordinate")
    delivery_latitude: float = Field(..., ge=-90.0, le=90.0, description="Delivery destination latitude")
    delivery_longitude: float = Field(..., ge=-180.0, le=180.0, description="Delivery destination longitude")
    order_date: str = Field(..., description="Order date formatted as DD-MM-YYYY or YYYY-MM-DD")
    order_time: str = Field(..., description="Order time formatted as HH:MM:SS")
    weather: WeatherCondition = Field(..., description="Current weather condition")
    traffic: TrafficDensity = Field(..., description="Current road traffic density")
    vehicle_condition: int = Field(default=1, ge=0, le=3, description="Vehicle condition rating (0 to 3)")
    type_of_order: OrderType = Field(..., description="Category of the food order")
    type_of_vehicle: VehicleType = Field(..., description="Rider's vehicle type")
    festival: FestivalType = Field(default=FestivalType.NO, description="Whether delivery occurs during a festival")
    city_type: CityType = Field(..., description="Urban classification of the delivery area")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "ORD-12345",
                "rider_id": "BANGRES19DEL01",
                "age": 28.0,
                "ratings": 4.8,
                "restaurant_latitude": 12.9716,
                "restaurant_longitude": 77.5946,
                "delivery_latitude": 13.0358,
                "delivery_longitude": 77.5970,
                "order_date": "15-03-2026",
                "order_time": "19:30:00",
                "weather": "sunny",
                "traffic": "medium",
                "vehicle_condition": 2,
                "type_of_order": "meal",
                "type_of_vehicle": "motorcycle",
                "festival": "no",
                "city_type": "metropolitan",
            }
        }
    }


class OrderPredictionResponse(BaseModel):
    """Normalized response payload for ETA service."""
    eta_minutes: float = Field(..., description="Estimated delivery time in minutes (point prediction)")
    lower_bound: float = Field(..., description="Lower bound of delivery interval (conformal / heuristic)")
    upper_bound: float = Field(..., description="Upper bound of delivery interval")
    model_version: str = Field(default="1.0.0", description="Registered model version serving prediction")
    feature_schema_version: str = Field(default=FEATURE_SCHEMA_VERSION, description="Feature contract schema version")
    degraded: bool = Field(default=False, description="True if fallback heuristic used due to model unavailability")
    latency_ms: float = Field(..., description="In-process inference latency in milliseconds")
    request_id: str | None = Field(default=None, description="Request correlation identifier")
