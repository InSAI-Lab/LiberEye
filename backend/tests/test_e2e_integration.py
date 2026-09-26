"""E2E integration tests for the cloud pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libereye.cloud_api import app, orchestrator
from scripts.e2e_test_client import MobileClient, MockBracelet, MockEarphone
from tests.e2e_fixtures import ensure_e2e_fixtures


@pytest.fixture
def client() -> TestClient:
    orchestrator.context_planner.history.clear()
    orchestrator.speech_suppression_count = 0
    orchestrator.fsm.state = "sidewalk"
    orchestrator.fsm._candidate = "sidewalk"
    orchestrator.fsm._candidate_count = 0
    return TestClient(app)


@pytest.fixture
def e2e_fixtures() -> list[dict]:
    fixtures_dir = Path(__file__).parent / "fixtures" / "e2e"
    return ensure_e2e_fixtures(fixtures_dir)


def _scenario(fixtures: list[dict], name_fragment: str) -> dict:
    for scenario in fixtures:
        if name_fragment in scenario["name"]:
            return scenario
    pytest.skip(f"E2E scenario missing: {name_fragment}")


def _post_image(client: TestClient, image_path: Path):
    with image_path.open("rb") as media_file:
        return client.post(
            "/api/mobile/analyze-media",
            files={"media": ("frame.jpg", media_file, "image/jpeg")},
        )


def test_e2e_response_schema(client: TestClient, e2e_fixtures: list[dict]) -> None:
    scenario = _scenario(e2e_fixtures, "sidewalk_normal")

    response = _post_image(client, scenario["input"])

    assert response.status_code == 200
    data = response.json()
    for field in [
        "priority",
        "voice_message",
        "bracelet",
        "output_actions",
        "spatial_audio",
        "avoidance_plan",
        "vision_backend",
        "should_speak",
        "agent_summary",
    ]:
        assert field in data
    assert data["priority"] in {"info", "warn", "danger"}
    assert data["vision_backend"] in {"heuristic", "ultralytics"}
    assert any(action["type"] == "ui_status" for action in data["output_actions"])


def test_e2e_sidewalk_normal(client: TestClient, e2e_fixtures: list[dict]) -> None:
    scenario = _scenario(e2e_fixtures, "sidewalk_normal")

    response = _post_image(client, scenario["input"])

    assert response.status_code == 200
    data = response.json()
    expected = scenario["expected"]
    assert data["priority"] == expected["priority"]
    assert data["vision_backend"] == expected["vision_backend"]
    assert data["should_speak"] is expected["should_speak"]
    assert data["voice_message"]
    assert data["bracelet"] is None or data["bracelet"]["risk_level"] == "info"


def test_e2e_crossing_red(client: TestClient, e2e_fixtures: list[dict]) -> None:
    scenario = _scenario(e2e_fixtures, "crossing_red")

    response = _post_image(client, scenario["input"])

    assert response.status_code == 200
    data = response.json()
    expected = scenario["expected"]
    assert data["priority"] == expected["priority"]
    assert data["voice_message"]
    assert data["bracelet"] is not None
    assert data["bracelet"]["pattern"] == expected["bracelet_pattern"]


def test_e2e_tactile_blocked(client: TestClient, e2e_fixtures: list[dict]) -> None:
    scenario = _scenario(e2e_fixtures, "tactile_blocked")

    response = _post_image(client, scenario["input"])

    assert response.status_code == 200
    data = response.json()
    expected = scenario["expected"]
    assert data["priority"] == expected["priority"]
    assert data["voice_message"]
    assert data["bracelet"] is not None


def test_e2e_mock_client_integration() -> None:
    client = MobileClient("http://localhost:8080", timeout=5.0)

    assert isinstance(client.earphone, MockEarphone)
    assert isinstance(client.bracelet, MockBracelet)
    heuristic_plan = client._local_heuristic()
    assert heuristic_plan["vision_backend"] == "unavailable"
    assert "voice_message" in heuristic_plan


def test_e2e_fallback_schema_consistency() -> None:
    fallback = MobileClient("http://localhost:8080")._local_heuristic()

    for field in [
        "priority",
        "voice_message",
        "bracelet",
        "spatial_audio",
        "avoidance_plan",
        "vision_backend",
        "should_speak",
        "context_reasoning",
        "reminder_trigger",
    ]:
        assert field in fallback
    assert fallback["vision_backend"] == "unavailable"
