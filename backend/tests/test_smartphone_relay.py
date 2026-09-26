from dataclasses import replace

from libereye.epmc import EPMCCoordinator
from libereye.mobile_contract import mobile_response
from libereye.models import SceneState
from libereye.smartphone_relay import format_smartphone_plan


def warning_plan():
    return EPMCCoordinator().analyze_scene(SceneState("warning", "optional scene detail", traffic_light="red", traffic_confidence=0.9))


def test_evidence_cannot_reintroduce_suppressed_speech():
    plan = warning_plan()
    evidence = {"scene_description": "private optional evidence", "vision_backend": {"active": True}}
    payload = mobile_response(plan, evidence)
    assert payload["description_gate"] is False
    assert payload["vision_backend"] == "ultralytics"
    assert payload["scene_description"] == evidence["scene_description"]
    assert payload["voice_message"] == plan.voice_message
    assert all("private optional evidence" not in action.get("message", "") for action in payload["output_actions"])


def test_disconnected_wrist_uses_speech_without_ble_dispatch():
    payload = format_smartphone_plan(warning_plan(), wrist_connected=False)
    assert not any(action["type"] == "ble_haptic" for action in payload["output_actions"])
    assert any(action["type"] == "tts" for action in payload["output_actions"])
    assert "fallback" in payload["voice_message"]


def test_relay_command_matches_firmware_bytes():
    payload = format_smartphone_plan(warning_plan())
    action = next(action for action in payload["output_actions"] if action["type"] == "ble_haptic")
    assert action["command_bytes"] == [7, 11, 184]
    assert action["duration_ms"] == 3000
    assert action["protocol"] == "libereye-wrist-v1"


def test_should_speak_is_respected():
    plan = warning_plan()
    plan = replace(plan, context_plan=replace(plan.context_plan, should_speak=False))
    payload = format_smartphone_plan(plan)
    assert payload["should_speak"] is False
    assert not any(action["type"] == "tts" for action in payload["output_actions"])
