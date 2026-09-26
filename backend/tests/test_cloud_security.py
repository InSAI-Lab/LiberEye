from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from libereye import cloud_api
from libereye.cloud_sessions import SessionStore


@pytest.fixture
def client():
    return TestClient(cloud_api.app)


def test_authentication_fails_closed(client, monkeypatch):
    monkeypatch.delenv("LIBEREYE_ALLOW_INSECURE")
    assert client.post("/api/mobile/analyze-perception", json={}).status_code == 503
    monkeypatch.setenv("LIBEREYE_API_TOKEN", "unit-test-token")
    assert client.post("/api/mobile/analyze-perception", json={}).status_code == 401
    assert client.post("/api/mobile/analyze-perception", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.post("/api/mobile/analyze-perception", json={}, headers={"Authorization": "Bearer unit-test-token"}).status_code == 200


def test_startup_requires_authentication(monkeypatch):
    monkeypatch.delenv("LIBEREYE_ALLOW_INSECURE")
    with pytest.raises(HTTPException, match="authentication"):
        with TestClient(cloud_api.app):
            pass


def test_health_never_exposes_model_errors(client, monkeypatch):
    monkeypatch.setattr(cloud_api.media_analyzer.vision_backend, "errors", ["private/path/token"])
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_error_count"] == 1
    assert "private/path/token" not in response.text


def test_sessions_are_isolated_and_missing_header_is_stateless(client):
    frame = {"scene_type": "sidewalk", "scene_description": "Test description", "obstacle_distance_m": 4.0}
    def post(sid):
        return client.post("/api/mobile/analyze-perception", json=frame, headers={"X-LiberEye-Session": sid}).json()
    first, second, other = post("walker-a"), post("walker-a"), post("walker-b")
    assert first["description_gate"] is True
    assert second["description_gate"] is False
    assert other["description_gate"] is True
    for _ in range(2):
        assert client.post("/api/mobile/analyze-perception", json=frame).json()["description_gate"] is True
    assert client.get("/api/epmc/metrics", headers={"X-LiberEye-Session": "walker-a"}).json()["total_updates"] == 2
    assert client.get("/api/epmc/metrics", headers={"X-LiberEye-Session": "walker-b"}).json()["total_updates"] == 1


def test_detail_requests_never_admit_descriptions_under_stop_override(client):
    response = client.post("/api/mobile/analyze-perception?detail_request=true&wrist_connected=false", json={
        "scene_type": "crossing", "traffic_light": "red", "scene_description": "Store advertising details", "user_intent": "cross",
    })
    data = response.json()
    assert data["wrist_cue"] == "W3"
    assert data["description_gate"] is False
    assert data["action_instruction"]
    assert "Store advertising details" not in data["voice_message"]
    assert not any(action["type"] == "ble_haptic" for action in data["output_actions"])
    assert any(action["type"] == "tts" for action in data["output_actions"])


@pytest.mark.parametrize("frame", [{"obstacle_distance_m": -1}, {"obstacle_confidence": 1.2}, {"traffic_confidence": -0.1}])
def test_invalid_perception_is_rejected(client, frame):
    assert client.post("/api/mobile/analyze-perception", json=frame).status_code == 422


def test_nonfinite_perception_is_rejected(client):
    assert client.post("/api/mobile/analyze-perception", content='{"obstacle_distance_m": NaN}', headers={"Content-Type": "application/json"}).status_code == 422


def test_invalid_session_identifier_is_rejected(client):
    assert client.post("/api/mobile/analyze-perception", json={}, headers={"X-LiberEye-Session": "a/b"}).status_code == 422


@pytest.mark.parametrize("filename,data,status", [("frame.exe", b"x", 415), ("frame.jpg", b"", 422), ("frame.jpg", b"bad jpeg", 422)])
def test_invalid_uploads_are_rejected_and_removed(client, monkeypatch, tmp_path, filename, data, status):
    monkeypatch.setattr(cloud_api.tempfile, "tempdir", str(tmp_path))
    assert client.post("/api/mobile/analyze-media", files={"media": (filename, data)}).status_code == status
    assert list(tmp_path.iterdir()) == []


def test_body_limit_prevents_parsing(client, monkeypatch):
    monkeypatch.setenv("LIBEREYE_MAX_UPLOAD_BYTES", "64")
    assert client.post("/api/mobile/analyze-media", files={"media": ("frame.jpg", b"x" * 100)}).status_code == 413


def test_chunked_body_limit(client, monkeypatch):
    monkeypatch.setenv("LIBEREYE_MAX_UPLOAD_BYTES", "32")
    chunks = iter([b'{"scene_description":"', b"x" * 80, b'"}'])
    response = client.post("/api/mobile/analyze-perception", content=chunks, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_large_decoded_image_is_rejected(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LIBEREYE_MAX_IMAGE_PIXELS", "10")
    monkeypatch.setattr(cloud_api.tempfile, "tempdir", str(tmp_path))
    image = BytesIO()
    Image.new("RGB", (10, 10)).save(image, format="PNG")
    assert client.post("/api/mobile/analyze-media", files={"media": ("test.png", image.getvalue())}).status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_required_models_fail_readiness(client, monkeypatch):
    monkeypatch.setenv("LIBEREYE_REQUIRE_MODELS", "1")
    assert client.get("/ready").status_code == 503


def test_busy_perception_rejects_stale_queue(client):
    image = BytesIO()
    Image.new("RGB", (10, 10)).save(image, format="PNG")
    with cloud_api._inference_lock:
        response = client.post("/api/mobile/analyze-media", files={"media": ("test.png", image.getvalue())})
    assert response.status_code == 503


def test_session_store_capacity_and_expiry(monkeypatch):
    store = SessionStore(capacity=1, ttl_s=1)
    with store.use("a") as coordinator:
        with pytest.raises(HTTPException):
            with store.use("b"):
                pass
    store._sessions["a"].last_used -= 2
    with store.use("b") as replacement:
        assert replacement is not coordinator
    assert list(store._sessions) == ["b"]


def test_session_updates_are_serialized():
    store = SessionStore()
    def update(_):
        with store.use("a") as coordinator:
            coordinator.total_updates += 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(update, range(100)))
    with store.use("a") as coordinator:
        assert coordinator.total_updates == 100
