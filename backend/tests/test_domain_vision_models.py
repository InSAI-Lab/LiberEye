from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from libereye.models import DetectedObject, SemanticRegion
from libereye.vision_backends import OptionalUltralyticsBackend, VisionModelOutputs


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "vision"


@pytest.fixture
def sample_frame() -> np.ndarray:
    return np.full((480, 640, 3), 128, dtype=np.uint8)


def _load_fixture(domain: str) -> np.ndarray:
    image_dir = FIXTURES_DIR / domain
    if not image_dir.exists():
        pytest.skip(f"Real {domain} fixtures not available")
    images = sorted(image_dir.glob("*.jpg")) + sorted(image_dir.glob("*.png"))
    if not images:
        pytest.skip(f"No {domain} fixture images found")
    try:
        import cv2
    except ImportError:
        pytest.skip("opencv-python not installed")
    frame = cv2.imread(str(images[0]))
    if frame is None:
        pytest.skip(f"Could not read fixture image: {images[0]}")
    return frame


@pytest.fixture
def real_tactile_frame() -> np.ndarray:
    return _load_fixture("tactile")


@pytest.fixture
def real_crosswalk_frame() -> np.ndarray:
    return _load_fixture("crosswalk")


@pytest.fixture
def real_traffic_light_frame() -> np.ndarray:
    return _load_fixture("traffic_light")


def _backend_with_env(env_name: str) -> OptionalUltralyticsBackend:
    if not os.getenv(env_name):
        pytest.skip(f"{env_name} not set")
    return OptionalUltralyticsBackend()


@pytest.fixture
def backend_with_tactile() -> OptionalUltralyticsBackend:
    return _backend_with_env("LIBEREYE_TACTILE_MODEL")


@pytest.fixture
def backend_with_crosswalk() -> OptionalUltralyticsBackend:
    return _backend_with_env("LIBEREYE_CROSSWALK_MODEL")


@pytest.fixture
def backend_with_traffic_light() -> OptionalUltralyticsBackend:
    return _backend_with_env("LIBEREYE_TRAFFIC_LIGHT_MODEL")


def test_tactile_model_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBEREYE_TACTILE_MODEL", "/tmp/tactile.pt")
    backend = OptionalUltralyticsBackend()
    assert backend.tactile_model_path == "/tmp/tactile.pt"
    assert backend.tactile_confidence == float(os.getenv("LIBEREYE_TACTILE_CONF", "0.18"))


def test_crosswalk_model_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBEREYE_CROSSWALK_MODEL", "/tmp/crosswalk.pt")
    backend = OptionalUltralyticsBackend()
    assert backend.crosswalk_model_path == "/tmp/crosswalk.pt"
    assert backend.crosswalk_confidence == float(os.getenv("LIBEREYE_CROSSWALK_CONF", "0.2"))


def test_traffic_light_model_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBEREYE_TRAFFIC_LIGHT_MODEL", "/tmp/traffic.pt")
    backend = OptionalUltralyticsBackend()
    assert backend.traffic_light_model_path == "/tmp/traffic.pt"
    assert backend.traffic_light_confidence == float(os.getenv("LIBEREYE_TRAFFIC_LIGHT_CONF", "0.2"))


def test_tactile_model_integration(backend_with_tactile: OptionalUltralyticsBackend, sample_frame: np.ndarray) -> None:
    outputs = backend_with_tactile.analyze(sample_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for region in [item for item in outputs.semantic_regions if item.label == "tactile_paving"]:
        assert isinstance(region, SemanticRegion)
        assert region.direction in {"left", "center", "right", "unknown"}
        assert 0.0 <= region.coverage <= 1.0
        assert 0.0 <= region.confidence <= 1.0


def test_tactile_model_with_real_fixture(
    backend_with_tactile: OptionalUltralyticsBackend, real_tactile_frame: np.ndarray
) -> None:
    outputs = backend_with_tactile.analyze(real_tactile_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for region in [item for item in outputs.semantic_regions if item.label == "tactile_paving"]:
        assert isinstance(region, SemanticRegion)
        assert 0.0 <= region.coverage <= 1.0


def test_crosswalk_model_integration(backend_with_crosswalk: OptionalUltralyticsBackend, sample_frame: np.ndarray) -> None:
    outputs = backend_with_crosswalk.analyze(sample_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for region in [item for item in outputs.semantic_regions if item.label == "crosswalk"]:
        assert isinstance(region, SemanticRegion)
        assert region.direction in {"left", "center", "right", "unknown"}
        assert 0.0 <= region.coverage <= 1.0
        assert 0.0 <= region.confidence <= 1.0


def test_crosswalk_model_with_real_fixture(
    backend_with_crosswalk: OptionalUltralyticsBackend, real_crosswalk_frame: np.ndarray
) -> None:
    outputs = backend_with_crosswalk.analyze(real_crosswalk_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for region in [item for item in outputs.semantic_regions if item.label == "crosswalk"]:
        assert isinstance(region, SemanticRegion)


def test_traffic_light_model_integration(
    backend_with_traffic_light: OptionalUltralyticsBackend, sample_frame: np.ndarray
) -> None:
    outputs = backend_with_traffic_light.analyze(sample_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for obj in [item for item in outputs.detected_objects if item.label.startswith("traffic_light")]:
        assert isinstance(obj, DetectedObject)
        assert obj.label in {"traffic_light", "traffic_light_red", "traffic_light_green", "traffic_light_yellow"}
        assert obj.direction in {"left", "center", "right", "unknown"}
        assert 0.0 <= obj.confidence <= 1.0
        if obj.distance_m is not None:
            assert obj.distance_m > 0.0


def test_traffic_light_model_with_real_fixture(
    backend_with_traffic_light: OptionalUltralyticsBackend, real_traffic_light_frame: np.ndarray
) -> None:
    outputs = backend_with_traffic_light.analyze(real_traffic_light_frame)
    assert isinstance(outputs, VisionModelOutputs)
    for obj in [item for item in outputs.detected_objects if item.label.startswith("traffic_light")]:
        assert isinstance(obj, DetectedObject)


def test_model_fallback_on_missing_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBEREYE_TACTILE_MODEL", "/nonexistent/model.pt")
    backend = OptionalUltralyticsBackend()
    assert any("tactile" in error.lower() for error in backend.errors)


def test_all_models_can_coexist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBEREYE_TACTILE_MODEL", "/tmp/tactile.pt")
    monkeypatch.setenv("LIBEREYE_CROSSWALK_MODEL", "/tmp/crosswalk.pt")
    monkeypatch.setenv("LIBEREYE_TRAFFIC_LIGHT_MODEL", "/tmp/traffic.pt")
    backend = OptionalUltralyticsBackend()
    assert backend.tactile_model_path is not None
    assert backend.crosswalk_model_path is not None
    assert backend.traffic_light_model_path is not None


@patch("libereye.vision_backends.OptionalUltralyticsBackend._analyze_tactile_model")
@patch("libereye.vision_backends.OptionalUltralyticsBackend._analyze_crosswalk_model")
@patch("libereye.vision_backends.OptionalUltralyticsBackend._analyze_traffic_light_model")
def test_model_fusion_with_mocks(
    mock_traffic: object,
    mock_crosswalk: object,
    mock_tactile: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_tactile.return_value = [
        SemanticRegion(label="tactile_paving", direction="center", coverage=0.4, confidence=0.85)
    ]
    mock_crosswalk.return_value = [
        SemanticRegion(label="crosswalk", direction="center", coverage=0.3, confidence=0.75)
    ]
    mock_traffic.return_value = [
        DetectedObject(label="traffic_light_red", direction="center", confidence=0.9, bbox=[100, 100, 50, 100])
    ]

    monkeypatch.setenv("LIBEREYE_ENABLE_STRONG_VISION", "1")
    backend = OptionalUltralyticsBackend()
    backend.yolo_model = object()
    outputs = backend.analyze(np.full((480, 640, 3), 128, dtype=np.uint8))

    assert isinstance(outputs, VisionModelOutputs)
    assert "tactile_paving" in {region.label for region in outputs.semantic_regions}
    assert "crosswalk" in {region.label for region in outputs.semantic_regions}
    assert "traffic_light_red" in {obj.label for obj in outputs.detected_objects}
    mock_tactile.assert_called_once()
    mock_crosswalk.assert_called_once()
    mock_traffic.assert_called_once()
