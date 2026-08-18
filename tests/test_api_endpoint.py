from contracts.features import FEATURE_SCHEMA_VERSION


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert data["service"] == "eta-service"


def test_ready_endpoint(client):
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "READY"
    assert data["feature_schema_version"] == FEATURE_SCHEMA_VERSION


def test_version_endpoint(client):
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert "model_version" in data


def test_predict_endpoint_valid_payload(client, valid_order_payload):
    response = client.post("/predict", json=valid_order_payload)
    assert response.status_code == 200
    data = response.json()

    assert "eta_minutes" in data
    assert isinstance(data["eta_minutes"], float)
    assert 5.0 <= data["eta_minutes"] <= 120.0
    assert data["lower_bound"] <= data["eta_minutes"] <= data["upper_bound"]
    assert data["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert "latency_ms" in data
    assert data["latency_ms"] >= 0.0
    assert "X-Correlation-ID" in response.headers


def test_predict_endpoint_validation_error_minor_age(client, valid_order_payload):
    bad_payload = valid_order_payload.copy()
    bad_payload["age"] = 15.0  # Minors rejected by Pydantic ge=18.0

    response = client.post("/predict", json=bad_payload)
    assert response.status_code == 422
    data = response.json()
    assert data["title"] == "Unprocessable Entity"
    assert "invalid_params" in data
    assert any("age" in str(err) for err in data["invalid_params"])


def test_predict_endpoint_validation_error_invalid_coordinates(client, valid_order_payload):
    bad_payload = valid_order_payload.copy()
    bad_payload["restaurant_latitude"] = 999.0  # Invalid latitude

    response = client.post("/predict", json=bad_payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == 422
    assert any("restaurant_latitude" in str(err) for err in data["invalid_params"])
