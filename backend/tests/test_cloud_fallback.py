"""Tests for cloud fallback behavior in the mock mobile client."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from scripts.e2e_test_client import MobileClient
from tests.e2e_fixtures import ensure_e2e_fixtures


@pytest.fixture
def test_image() -> Path:
    fixtures = ensure_e2e_fixtures(Path(__file__).parent / "fixtures" / "e2e")
    if not fixtures:
        pytest.skip("No E2E fixtures available")
    return fixtures[0]["input"]


def test_timeout_triggers_fallback(test_image: Path) -> None:
    client = MobileClient("http://localhost:8080", timeout=0.1)

    with patch.object(client, "_call_cloud", side_effect=httpx.TimeoutException("timeout")):
        plan = client.process_frame(test_image)

    assert client.fallback_mode is True
    assert plan["vision_backend"] == "unavailable"
    assert plan["voice_message"]


def test_fallback_response_schema(test_image: Path) -> None:
    client = MobileClient("http://localhost:8080", timeout=0.1)

    with patch.object(client, "_call_cloud", side_effect=httpx.ConnectError("down")):
        plan = client.process_frame(test_image)

    for field in [
        "priority",
        "main_instruction",
        "voice_message",
        "bracelet",
        "spatial_audio",
        "avoidance_plan",
        "context_reasoning",
        "reminder_trigger",
        "should_speak",
        "vision_backend",
        "agent_summary",
    ]:
        assert field in plan
    assert plan["vision_backend"] == "unavailable"
    assert plan["priority"] in {"info", "warn", "danger"}


def test_health_probe_recovery(test_image: Path) -> None:
    client = MobileClient("http://localhost:8080", timeout=5.0)
    client.fallback_mode = True
    client.last_health_check = time.time() - 31.0

    with patch.object(client, "_check_cloud_health", return_value=True):
        with patch.object(
            client,
            "_call_cloud",
            return_value={
                "priority": "info",
                "voice_message": "cloud restored",
                "bracelet": None,
                "vision_backend": "heuristic",
                "should_speak": True,
            },
        ):
            plan = client.process_frame(test_image)

    assert client.fallback_mode is False
    assert plan["voice_message"] == "cloud restored"


def test_user_notification(test_image: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = MobileClient("http://localhost:8080", timeout=0.1)

    with patch.object(client, "_call_cloud", side_effect=httpx.TimeoutException("timeout")):
        client.process_frame(test_image)

    captured = capsys.readouterr()
    assert "Cloud unavailable; stop and confirm surroundings" in captured.out

    client.last_health_check = time.time() - 31.0
    with patch.object(client, "_check_cloud_health", return_value=True):
        with patch.object(
            client,
            "_call_cloud",
            return_value={"priority": "info", "voice_message": "ok", "bracelet": None, "vision_backend": "heuristic", "should_speak": True},
        ):
            client.process_frame(test_image)

    captured = capsys.readouterr()
    assert "Network restored" in captured.out


def test_fallback_voice_output(test_image: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = MobileClient("http://localhost:8080", timeout=0.1)

    with patch.object(client, "_call_cloud", side_effect=httpx.ConnectError("down")):
        plan = client.process_frame(test_image)

    captured = capsys.readouterr()
    assert "[EARPHONE] TTS:" in captured.out
    assert plan["voice_message"] in captured.out


def test_retry_logic(test_image: Path) -> None:
    client = MobileClient("http://localhost:8080", timeout=0.1)

    with patch.object(client, "_call_cloud", side_effect=httpx.TimeoutException("timeout")) as call:
        client.process_frame(test_image)

    assert call.call_count == 2
    assert client.fallback_mode is True


def test_health_check_interval(test_image: Path) -> None:
    client = MobileClient("http://localhost:8080")
    client.fallback_mode = True
    client.last_health_check = time.time()

    with patch.object(client, "_check_cloud_health", return_value=True) as health:
        plan = client.process_frame(test_image)

    assert health.call_count == 0
    assert client.fallback_mode is True
    assert plan["vision_backend"] == "unavailable"


def test_unavailable_notice_never_claims_safe_passage():
    plan = MobileClient("http://localhost:8080")._local_heuristic()
    assert plan["priority"] == "danger"
    assert plan["avoidance_plan"]["action"] == "stop"
    assert plan["avoidance_plan"]["confidence"] == 0
    assert "unavailable" in plan["voice_message"]
    assert "Continue straight" not in plan["voice_message"]
    assert "Road conditions normal" not in plan["voice_message"]


def test_mock_client_executes_only_admitted_actions():
    client = MobileClient("http://localhost:8080")
    with patch.object(client.earphone, "play_tts") as tts, patch.object(client.bracelet, "vibrate") as vibrate:
        client._dispatch_outputs({"should_speak": False, "voice_message": "not admitted", "priority": "info", "output_actions": [
            {"type": "tts", "message": "not admitted"},
            {"type": "ble_haptic", "pattern": "D1", "intensity": 25},
        ]})
    tts.assert_not_called()
    vibrate.assert_called_once_with("D1", 25)
