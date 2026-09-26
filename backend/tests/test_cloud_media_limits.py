"""Regression tests for model failure admission and decoded media bounds."""
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from libereye import cloud_api
from libereye.media_analyzer import MediaAnalyzer
from libereye.models import PerceptionFrame


def png_bytes(width=10, height=10):
    stream = BytesIO()
    Image.new("RGB", (width, height)).save(stream, format="PNG")
    return stream.getvalue()


def test_prediction_failure_rejects_current_required_model_request(monkeypatch, tmp_path):
    backend = cloud_api.media_analyzer.vision_backend
    for name in ("yolo", "tactile", "crosswalk", "traffic_light"):
        monkeypatch.setattr(backend, f"{name}_model", object())
    monkeypatch.setattr(backend, "errors", [])
    monkeypatch.setenv("LIBEREYE_REQUIRE_MODELS", "1")
    monkeypatch.setattr(cloud_api.tempfile, "tempdir", str(tmp_path))

    def failing_prediction(*args, **kwargs):
        backend.errors.append("YOLO predict failed: simulated failure")
        return PerceptionFrame(scene_type="sidewalk"), {}

    monkeypatch.setattr(cloud_api.media_analyzer, "analyze_file", failing_prediction)
    with TestClient(cloud_api.app) as client:
        assert client.get("/ready").status_code == 200
        response = client.post("/api/mobile/analyze-media", files={"media": ("frame.png", png_bytes())})
    assert response.status_code == 503
    assert "voice_message" not in response.json()
    assert list(tmp_path.iterdir()) == []
    assert not cloud_api._inference_lock.locked()


def test_video_extension_cannot_bypass_still_image_pixel_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("LIBEREYE_MAX_IMAGE_PIXELS", "10")
    monkeypatch.setattr(cloud_api.tempfile, "tempdir", str(tmp_path))
    with TestClient(cloud_api.app) as client:
        response = client.post("/api/mobile/analyze-media", files={"media": ("frame.mp4", png_bytes())})
    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


class Capture:
    def __init__(self, width=2, height=2, frame=None, opened=True):
        self.width = width
        self.height = height
        self.frame = frame if frame is not None else np.zeros((2, 2, 3), dtype=np.uint8)
        self.opened = opened
        self.released = False
        self.read_count = 0

    def isOpened(self):
        return self.opened

    def get(self, key):
        return {cv2.CAP_PROP_FRAME_WIDTH: self.width, cv2.CAP_PROP_FRAME_HEIGHT: self.height,
                cv2.CAP_PROP_FRAME_COUNT: 8}.get(key, 0)

    def set(self, key, value):
        return True

    def read(self):
        self.read_count += 1
        return True, self.frame

    def release(self):
        self.released = True


def test_true_video_metadata_is_checked_before_frame_decode(monkeypatch, tmp_path):
    monkeypatch.setenv("LIBEREYE_MAX_IMAGE_PIXELS", "10")
    capture = Capture(width=10, height=10)
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: capture)
    path = tmp_path / "frame.mp4"
    path.write_bytes(b"video fixture")
    with pytest.raises(ValueError, match="pixel limit"):
        cloud_api._validate_media(path)
    assert capture.read_count == 0
    assert capture.released is True


def test_video_checks_each_decoded_frame_and_releases_on_rejection(monkeypatch):
    monkeypatch.setenv("LIBEREYE_MAX_IMAGE_PIXELS", "10")
    capture = Capture(frame=np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: capture)
    with pytest.raises(ValueError, match="pixel limit"):
        MediaAnalyzer()._analyze_video(Path("frame.mp4"), None)
    assert capture.read_count == 1
    assert capture.released is True


def test_video_releases_decoder_when_analysis_raises(monkeypatch):
    capture = Capture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: capture)
    analyzer = MediaAnalyzer()
    def fail(*args, **kwargs):
        raise ValueError("analysis failed")
    monkeypatch.setattr(analyzer, "_analyze_frame", fail)
    with pytest.raises(ValueError, match="analysis failed"):
        analyzer._analyze_video(Path("frame.mp4"), None)
    assert capture.released is True


def test_video_still_samples_at_most_eight_frames(monkeypatch):
    capture = Capture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: capture)
    analyzer = MediaAnalyzer()
    monkeypatch.setattr(analyzer, "_analyze_frame", lambda *args, **kwargs: (PerceptionFrame(), {}))
    _, evidence = analyzer._analyze_video(Path("frame.mp4"), None)
    assert capture.read_count == 8
    assert evidence["sampled_frames"] == 8
    assert capture.released is True
