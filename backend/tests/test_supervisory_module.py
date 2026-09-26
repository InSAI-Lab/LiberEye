"""Unit tests for SupervisoryModule override evaluations.

Corresponds to ICASSP 2027 paper Section 2.2.
"""
from __future__ import annotations

import time

from libereye.models import SceneState, SemanticRegion
from libereye.supervisory_module import SupervisoryModule


def test_supervisory_sensor_lost_triggers_override():
    sup = SupervisoryModule()
    scene = SceneState(
        name="test_lost",
        description="test",
        sensor_health="lost",
    )
    dec = sup.evaluate(scene)
    assert dec.override is True
    assert dec.fused_severity == "danger"
    assert dec.override_wrist_cue == "W3"
    assert "sensor disconnected" in " ".join(dec.notes)


def test_supervisory_traffic_hazard_triggers_override():
    sup = SupervisoryModule()
    scene = SceneState(
        name="test_red",
        description="test",
        traffic_light="red",
        traffic_confidence=0.9,
    )
    dec = sup.evaluate(scene)
    assert dec.override is True
    assert dec.fused_severity == "danger"
    assert dec.override_wrist_cue == "W3"
    assert "Red light" in dec.stop_instruction


def test_supervisory_roadway_deviation_triggers_override():
    sup = SupervisoryModule()
    scene = SceneState(
        name="test_road",
        description="test",
        semantic_regions=[SemanticRegion(label="road_or_asphalt", direction="center", coverage=0.25)],
        user_intent="navigate",  # Not intending to cross
    )
    dec = sup.evaluate(scene)
    assert dec.override is True
    assert dec.override_wrist_cue == "W3"


def test_supervisory_safe_scene_no_override():
    sup = SupervisoryModule()
    scene = SceneState(
        name="test_safe",
        description="test",
        traffic_light="green",
        traffic_confidence=0.9,
        user_intent="navigate",
        sensor_health="ok",
    )
    dec = sup.evaluate(scene)
    assert dec.override is False
    assert dec.override_wrist_cue is None


def test_invalid_and_stale_observation_time_stops():
    for timestamp in (float("nan"), float("inf"), time.time() + 60, time.time() - 10):
        decision = SupervisoryModule().evaluate(SceneState("test", "test", timestamp_s=timestamp))
        assert decision.override is True
        assert decision.override_wrist_cue == "W3"


def test_immediate_risk_requires_its_own_confidence():
    from libereye.models import DepthEstimate
    supervisor = SupervisoryModule()
    scene = SceneState("test", "test", obstacle_distance_m=2, obstacle_confidence=0.9,
                       depth_estimate=DepthEstimate(center_depth_m=0.3, confidence=0.1))
    assert supervisor.evaluate(scene).override is False
    close_scene = SceneState("test", "test", obstacle_distance_m=0.3, obstacle_confidence=0.9)
    assert supervisor.evaluate(close_scene).override is True
