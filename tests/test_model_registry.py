import json
from pathlib import Path


def test_registry_report():
    root_path = Path(__file__).parent.parent
    report_path = root_path / "reports" / "registry.json"
    assert report_path.exists(), "Registry report must exist from register_model stage"

    with open(report_path, "r") as f:
        data = json.load(f)

    assert data["model_name"] == "delivery_time_pred_model"
    assert data["alias"] == "champion"
    assert data["status"] == "READY"
