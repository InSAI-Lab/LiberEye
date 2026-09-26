"""Continuous frame flow tests for the cloud API."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from libereye.cloud_api import app, orchestrator
from tests.e2e_fixtures import ensure_e2e_fixtures


@pytest.fixture
def client() -> TestClient:
    _reset_orchestrator()
    return TestClient(app, headers={"X-LiberEye-Session": "continuous-test"})


@pytest.fixture
def e2e_images() -> list[Path]:
    fixtures = ensure_e2e_fixtures(Path(__file__).parent / "fixtures" / "e2e")
    return [scenario["input"] for scenario in fixtures]


def _reset_orchestrator() -> None:
    orchestrator.context_planner.history.clear()
    orchestrator.speech_suppression_count = 0
    orchestrator.alert_latency_ms_samples.clear()
    orchestrator._total_frames = 0
    orchestrator._conflict_frames = 0
    orchestrator.event_conflict_rate = 0.0
    orchestrator.fsm.state = "sidewalk"
    orchestrator.fsm._candidate = "sidewalk"
    orchestrator.fsm._candidate_count = 0


def _post_image(client: TestClient, image_path: Path, index: int = 0):
    with image_path.open("rb") as media_file:
        return client.post(
            "/api/mobile/analyze-media",
            files={"media": (f"frame_{index}.jpg", media_file, "image/jpeg")},
        )


def test_continuous_frames_stability(client: TestClient, e2e_images: list[Path]) -> None:
    image = e2e_images[0]
    errors: list[str] = []

    for index in range(30):
        try:
            response = _post_image(client, image, index)
            assert response.status_code == 200
            payload = response.json()
            assert "priority" in payload
            assert "voice_message" in payload
            assert "vision_backend" in payload
        except Exception as exc:
            errors.append(f"frame {index}: {exc}")

    assert errors == []


def test_suppression_count_increases(client: TestClient, e2e_images: list[Path]) -> None:
    image = e2e_images[0]

    for index in range(10):
        response = _post_image(client, image, index)
        assert response.status_code == 200

    assert client.get("/api/epmc/metrics").json()["speech_suppression_count"] > 0


def test_descriptions_withheld_but_actions_remain_eligible_on_stable(client: TestClient, e2e_images: list[Path]) -> None:
    image = e2e_images[0]
    responses = []

    for index in range(10):
        response = _post_image(client, image, index)
        assert response.status_code == 200
        responses.append(response.json())

    later_frames = responses[5:]
    suppressed_count = sum(1 for payload in later_frames if not payload["description_gate"])
    assert suppressed_count > 0


def test_scene_change_resets_suppression(client: TestClient, e2e_images: list[Path]) -> None:
    if len(e2e_images) < 2:
        pytest.skip("Need at least two scenario fixtures")

    stable = e2e_images[0]
    changed = e2e_images[1]
    for index in range(5):
        response = _post_image(client, stable, index)
        assert response.status_code == 200

    response = _post_image(client, changed, 99)
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("should_speak", False) or payload.get("reminder_trigger") in {"urgent", "update"}


def test_continuous_frames_latency_consistency(client: TestClient, e2e_images: list[Path]) -> None:
    image = e2e_images[0]
    latencies: list[float] = []

    for index in range(20):
        start = time.perf_counter()
        response = _post_image(client, image, index)
        latencies.append((time.perf_counter() - start) * 1000.0)
        assert response.status_code == 200

    first_half_avg = sum(latencies[:10]) / 10
    second_half_avg = sum(latencies[10:]) / 10
    assert second_half_avg < max(first_half_avg * 2.5, first_half_avg + 50.0)
