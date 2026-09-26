from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from libereye.cloud_api import app, media_analyzer


def test_cloud_health():
    client = TestClient(app)

    response = client.get("/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["service"] == "libereye-cloud"
    assert payload["version"] == app.version
    assert payload["models_loaded"] == {
        "tactile": False,
        "crosswalk": False,
        "traffic_light": False,
    }
    assert isinstance(payload["gpu_available"], bool)


def test_cloud_health_reports_loaded_models(monkeypatch):
    client = TestClient(app)
    backend = media_analyzer.vision_backend

    monkeypatch.setattr(backend, "tactile_model", object())
    monkeypatch.setattr(backend, "crosswalk_model", object())
    monkeypatch.setattr(backend, "traffic_light_model", object())
    monkeypatch.setattr(backend, "errors", [])

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["models_loaded"] == {
        "tactile": True,
        "crosswalk": True,
        "traffic_light": True,
    }


def test_cloud_health_degraded_when_backend_has_errors(monkeypatch):
    client = TestClient(app)
    backend = media_analyzer.vision_backend

    monkeypatch.setattr(backend, "errors", ["model load failed"])

    response = client.get("/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["model_error_count"] == 1


def test_mobile_media_endpoint_returns_compact_guidance(tmp_path: Path):
    image = np.full((360, 480, 3), 220, dtype=np.uint8)
    cv2.rectangle(image, (190, 230), (290, 350), (35, 35, 35), -1)
    path = tmp_path / "frame.png"
    cv2.imwrite(str(path), image)
    client = TestClient(app)

    with path.open("rb") as media_file:
        response = client.post(
            "/api/mobile/analyze-media",
            files={"media": ("frame.png", media_file, "image/png")},
        )

    payload = response.json()
    assert response.status_code == 200
    assert "main_instruction" in payload
    assert "scene_brief" in payload
    assert "risk_brief" in payload
    assert "next_action" in payload
    assert "bracelet" in payload
    assert "output_actions" in payload
    assert "spatial_audio" in payload
    assert "avoidance_plan" in payload
    assert "agent_summary" in payload


def test_mobile_contract_sends_haptic_before_concise_speech():
    client = TestClient(app)

    response = client.post(
        "/api/mobile/analyze-perception",
        json={
            "scene_type": "sidewalk",
            "obstacle_distance_m": 1.1,
            "obstacle_confidence": 0.9,
            "sensor_health": "ok",
        },
    )

    payload = response.json()
    actions = payload["output_actions"]
    assert response.status_code == 200
    assert payload["scene_brief"]
    assert payload["risk_brief"] in {"Caution", "High risk"}
    assert payload["next_action"]
    assert len(payload["voice_message"].split()) <= 20
    assert actions[0]["type"] == "ble_haptic"
    assert actions[1]["type"] == "tts"


def test_mobile_perception_endpoint_returns_same_compact_contract():
    client = TestClient(app)

    response = client.post(
        "/api/mobile/analyze-perception?source=doubao",
        json={
            "scene_type": "crossing",
            "traffic_light": "red",
            "traffic_confidence": 0.92,
            "vehicle_approaching": True,
            "vehicle_confidence": 0.88,
            "user_intent": "cross",
            "detected_objects": [
                {"label": "car", "direction": "center", "distance_m": 5.0, "confidence": 0.86}
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["source"] == "doubao"
    assert payload["priority"] == "danger"
    assert payload["bracelet"]["risk_level"] == "danger"
    haptic_actions = [action for action in payload["output_actions"] if action["type"] == "ble_haptic"]
    assert haptic_actions
    assert haptic_actions[0]["command"].startswith(payload["bracelet"]["pattern"])
    assert payload["should_speak"] is True
    assert payload["vision_backend"] == "doubao"
    assert "agent_summary" in payload


def test_mobile_perception_endpoint_accepts_phone_safety_signal():
    client = TestClient(app)

    response = client.post(
        "/api/mobile/analyze-perception",
        json={
            "scene_type": "sidewalk",
            "obstacle_distance_m": 1.2,
            "obstacle_confidence": 0.94,
            "sensor_health": "ok",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["source"] == "structured"
    assert payload["priority"] in {"warn", "danger"}
    assert payload["bracelet"] is not None


def test_structured_tactile_hazard_is_not_lost_by_media_fixture_limitations():
    response = TestClient(app).post("/api/mobile/analyze-perception?detail_request=true", json={
        "scene_type": "blocked", "tactile_blocked": True, "tactile_confidence": 0.9,
        "scene_description": "Store details that must not be spoken",
    })
    assert response.status_code == 200
    plan = response.json()
    assert plan["wrist_cue"] == "W1"
    assert plan["priority"] == "warn"
    assert plan["description_gate"] is False
    assert "Store details" not in plan["voice_message"]


def test_structured_target_query_does_not_default_to_a_confirmed_detection():
    client = TestClient(app)
    for observation in [
        {"target_query": "cup"},
        {"target_query": "cup", "target_direction": "right", "target_distance_m": 2.0},
    ]:
        response = client.post("/api/live", json=observation)
        assert response.status_code == 200
        plan = response.json()
        assert not any(event["metadata"].get("target_query") == "cup" for event in plan["mobility_events"])
        assert "Found target cup" not in plan["voice_message"]
        assert plan["haptics"] == []
