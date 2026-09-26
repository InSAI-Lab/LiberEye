"""Tests for WiFi frame reception and the /api/glasses/frame endpoint."""
from __future__ import annotations

import io
import numpy as np
import cv2

from fastapi.testclient import TestClient

from libereye.cloud_api import app, glasses_receiver
from libereye.glasses import GlassesWifiReceiver


client = TestClient(app)


def _make_jpeg_bytes() -> bytes:
    """Create a minimal valid JPEG image for testing."""
    image = np.full((64, 64, 3), 128, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (54, 54), (50, 50, 50), -1)
    _, buf = cv2.imencode(".jpg", image)
    return buf.tobytes()


# WiFi frame ingestion
def test_glasses_frame_endpoint_accepts_jpeg():
    """POST /api/glasses/frame with a valid JPEG returns 200 with AssistancePlan fields."""
    jpeg = _make_jpeg_bytes()
    response = client.post(
        "/api/glasses/frame",
        files={"frame": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "priority" in data
    assert "main_instruction" in data
    assert "voice_message" in data
    assert "should_speak" in data
    assert "glasses_connected" in data
    assert data["glasses_connected"] is True


def test_glasses_frame_endpoint_returns_metadata():
    """POST /api/glasses/frame response includes metadata with agent metrics."""
    jpeg = _make_jpeg_bytes()
    response = client.post(
        "/api/glasses/frame",
        files={"frame": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "metadata" in data
    assert "description_gate" in data["metadata"]


def test_glasses_frame_endpoint_with_target_query():
    """POST /api/glasses/frame with target_query passes it through."""
    jpeg = _make_jpeg_bytes()
    response = client.post(
        "/api/glasses/frame",
        files={"frame": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
        data={"target_query": "cup"},
    )
    assert response.status_code == 200


def test_glasses_frame_endpoint_requires_frame_field():
    """POST /api/glasses/frame without 'frame' field returns 422."""
    response = client.post("/api/glasses/frame")
    assert response.status_code == 422


# GlassesWifiReceiver class
def test_glasses_wifi_receiver_ingest_jpeg():
    """GlassesWifiReceiver.ingest_jpeg processes JPEG and returns PerceptionFrame."""
    receiver = GlassesWifiReceiver()
    jpeg = _make_jpeg_bytes()
    frame, evidence = receiver.ingest_jpeg(jpeg)
    assert frame is not None
    assert receiver.connected is True
    assert evidence.get("glasses_source") == "wifi"


def test_glasses_wifi_receiver_marks_connected():
    """GlassesWifiReceiver.connected becomes True after ingest_jpeg."""
    receiver = GlassesWifiReceiver()
    assert receiver.connected is False  # initially not connected
    jpeg = _make_jpeg_bytes()
    receiver.ingest_jpeg(jpeg)
    assert receiver.connected is True


# Disconnect fallback
def test_glasses_wifi_receiver_timeout_sets_disconnected():
    """GlassesWifiReceiver.check_timeout() sets connected=False after timeout."""
    receiver = GlassesWifiReceiver(disconnect_timeout_s=0.001)
    jpeg = _make_jpeg_bytes()
    receiver.ingest_jpeg(jpeg)
    assert receiver.connected is True
    import time
    time.sleep(0.01)  # wait for timeout
    timed_out = receiver.check_timeout()
    assert timed_out is True
    assert receiver.connected is False


def test_glasses_frame_endpoint_no_auth_when_token_not_set():
    """Without LIBEREYE_API_TOKEN set, endpoint accepts requests without auth."""
    import os
    original = os.environ.pop("LIBEREYE_API_TOKEN", None)
    try:
        jpeg = _make_jpeg_bytes()
        response = client.post(
            "/api/glasses/frame",
            files={"frame": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
        )
        assert response.status_code == 200
    finally:
        if original is not None:
            os.environ["LIBEREYE_API_TOKEN"] = original


def test_glasses_frame_endpoint_rejects_wrong_token():
    """With LIBEREYE_API_TOKEN set, wrong token returns 403."""
    import os
    os.environ["LIBEREYE_API_TOKEN"] = "correct-token"
    try:
        jpeg = _make_jpeg_bytes()
        response = client.post(
            "/api/glasses/frame",
            files={"frame": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 403
    finally:
        del os.environ["LIBEREYE_API_TOKEN"]


def test_mobile_analyze_media_unaffected_by_glasses_state():
    """POST /api/mobile/analyze-media works regardless of glasses_connected state."""
    jpeg = _make_jpeg_bytes()
    # Simulate glasses disconnected
    glasses_receiver.connected = False
    response = client.post(
        "/api/mobile/analyze-media",
        files={"media": ("frame.jpg", io.BytesIO(jpeg), "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "priority" in data
