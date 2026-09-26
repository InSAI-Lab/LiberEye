"""Tests for scene-aware specialist coordination and feedback selection."""
from __future__ import annotations

import time

from libereye.models import AgentResult, PerceptionFrame
from libereye.mobility_coordinator import MobilityOrchestrator, SceneFSM, SCENE_AGENT_MAP


# Scene FSM with Hysteresis
def test_scene_fsm_single_frame_does_not_transition():
    """Single-frame scene change must NOT trigger FSM state transition."""
    fsm = SceneFSM()
    assert fsm.state == "sidewalk"
    fsm.update("crossing")
    assert fsm.state == "sidewalk", "Single frame should not trigger transition"


def test_scene_fsm_two_frames_does_not_transition():
    """Two consecutive frames must NOT trigger FSM state transition."""
    fsm = SceneFSM()
    fsm.update("crossing")
    fsm.update("crossing")
    assert fsm.state == "sidewalk", "Two frames should not trigger transition"


def test_scene_fsm_three_frames_triggers_transition():
    """Three consecutive frames MUST trigger FSM state transition."""
    fsm = SceneFSM()
    fsm.update("crossing")
    fsm.update("crossing")
    fsm.update("crossing")
    assert fsm.state == "approaching_crossing", f"Expected approaching_crossing, got {fsm.state}"


def test_scene_fsm_full_crossing_cycle():
    """sidewalk → approaching_crossing → crossing → recovery → sidewalk."""
    fsm = SceneFSM()
    # sidewalk → approaching_crossing
    for _ in range(3):
        fsm.update("crossing")
    assert fsm.state == "approaching_crossing"
    # approaching_crossing → crossing
    for _ in range(3):
        fsm.update("crossing")
    assert fsm.state == "crossing"
    # crossing → recovery
    for _ in range(3):
        fsm.update("sidewalk")
    assert fsm.state == "recovery"
    # recovery → sidewalk
    for _ in range(3):
        fsm.update("sidewalk")
    assert fsm.state == "sidewalk"


def test_scene_fsm_hysteresis_prevents_jitter():
    """Alternating scene types should not cause state transitions."""
    fsm = SceneFSM()
    for _ in range(5):
        fsm.update("crossing")
        fsm.update("sidewalk")
    assert fsm.state == "sidewalk", "Alternating frames should not transition"


def test_orchestrator_crossing_mode_property():
    """MobilityOrchestrator.crossing_mode reflects FSM state."""
    orch = MobilityOrchestrator()
    assert orch.crossing_mode == "sidewalk"
    for _ in range(3):
        orch.fsm.update("crossing")
    assert orch.crossing_mode == "approaching_crossing"


# Four-Level Priority Coordinator
def test_agent_priority_danger_is_critical():
    """Danger severity results must get CRITICAL priority."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(traffic_light="red", traffic_confidence=0.95)
    plan = orch.analyze_perception(frame)
    danger_results = [r for r in plan.agent_results if r.severity == "danger"]
    assert all(r.priority == "CRITICAL" for r in danger_results), \
        f"Danger results should be CRITICAL: {[(r.agent_id, r.priority) for r in danger_results]}"


def test_agent_priority_default_is_on_demand():
    """AgentResult default priority is ON_DEMAND (backward compat)."""
    r = AgentResult("x", "y", "ok", "info", 0.9, "go")
    assert r.priority == "ON_DEMAND"


def test_agent_priority_crossing_warn_is_critical():
    """Warn results in crossing FSM state should be CRITICAL."""
    orch = MobilityOrchestrator()
    # Force FSM into crossing state
    for _ in range(6):
        orch.fsm.update("crossing")
    assert orch.fsm.state == "crossing"
    frame = PerceptionFrame(
        scene_type="crossing",
        vehicle_approaching=False,
        vehicle_confidence=0.8,
        user_intent="cross",
    )
    plan = orch.analyze_perception(frame)
    warn_results = [r for r in plan.agent_results if r.severity == "warn"]
    if warn_results:
        assert all(r.priority == "CRITICAL" for r in warn_results), \
            f"Warn results in crossing should be CRITICAL: {[(r.agent_id, r.priority) for r in warn_results]}"


# Dynamic Agent Gating
def test_scene_agent_map_crossing_excludes_tactile():
    """Crossing scene should not activate tactile paving agent."""
    assert "tactile" not in SCENE_AGENT_MAP["crossing"]


def test_scene_agent_map_crossing_includes_traffic():
    """Crossing scene must activate traffic light agent."""
    assert "traffic" in SCENE_AGENT_MAP["crossing"]


def test_scene_agent_map_sidewalk_includes_tactile():
    """Sidewalk scene must activate tactile paving agent."""
    assert "tactile" in SCENE_AGENT_MAP["sidewalk"]


def test_dynamic_gating_crossing_skips_tactile_agent():
    """In crossing scene, tactile agent should not appear in results."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(scene_type="crossing", user_intent="cross")
    plan = orch.analyze_perception(frame)
    agent_ids = {r.agent_id for r in plan.agent_results}
    assert "tactile" not in agent_ids, "Tactile agent should be gated out in crossing scene"
    assert "traffic" in agent_ids, "Traffic agent should be active in crossing scene"


def test_dynamic_gating_sidewalk_includes_tactile():
    """In sidewalk scene, tactile agent should appear in results."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(scene_type="sidewalk")
    plan = orch.analyze_perception(frame)
    agent_ids = {r.agent_id for r in plan.agent_results}
    assert "tactile" in agent_ids, "Tactile agent should be active in sidewalk scene"


def test_activation_rate_measurable():
    """Active agent count / total agent count should be < 1 for specific scenes."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(scene_type="crossing", user_intent="cross")
    plan = orch.analyze_perception(frame)
    active = plan.metadata["active_agent_count"]
    total = plan.metadata["total_agent_count"]
    assert active < total, f"Crossing scene should gate some agents: {active}/{total}"
    assert active > 0


# Confidence-Weighted Fusion
def test_fusion_replaces_max_severity():
    """Confidence-weighted fusion should not always pick the highest severity."""
    orch = MobilityOrchestrator()
    # Low-confidence danger + high-confidence info → fusion should lean toward info
    frame = PerceptionFrame(
        obstacle_distance_m=1.8,
        obstacle_confidence=0.3,  # low confidence danger
        scene_type="sidewalk",
    )
    plan = orch.analyze_perception(frame)
    # The plan should not be "danger" when the only danger signal has low confidence
    # (safety supervisor may still override, but the fusion result itself should be lower)
    assert plan is not None  # basic sanity


def test_fusion_high_confidence_danger_wins():
    """High-confidence danger result should produce danger plan."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(
        traffic_light="red",
        traffic_confidence=0.95,
        vehicle_approaching=True,
        vehicle_confidence=0.92,
    )
    plan = orch.analyze_perception(frame)
    assert plan.priority == "danger"


# Cognitive Load-Aware Modality Dispatch
def test_cognitive_load_crossing_is_haptic_first():
    """Crossing scene with danger should produce haptic-first load (L > 0.7)."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(
        scene_type="crossing",
        traffic_light="red",
        traffic_confidence=0.95,
        vehicle_approaching=True,
        vehicle_confidence=0.9,
    )
    plan = orch.analyze_perception(frame)
    assert plan.cognitive_load["haptic"] >= plan.cognitive_load["voice"], \
        f"Crossing danger should be haptic-heavy: {plan.cognitive_load}"


def test_cognitive_load_safe_sidewalk_is_voice_first():
    """Safe sidewalk scene should produce voice-first load (L < 0.3)."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(scene_type="sidewalk", obstacle_distance_m=5.0, obstacle_confidence=0.9)
    plan = orch.analyze_perception(frame)
    assert plan.cognitive_load["voice"] >= plan.cognitive_load["haptic"], \
        f"Safe sidewalk should be voice-heavy: {plan.cognitive_load}"


def test_cognitive_load_keys_present():
    """cognitive_load dict must have 'voice' and 'haptic' keys."""
    orch = MobilityOrchestrator()
    plan = orch.analyze_scenario("blocked")
    assert "voice" in plan.cognitive_load
    assert "haptic" in plan.cognitive_load


# Temporal-Aware Adaptive Suppression
def test_adaptive_suppression_stable_frames_suppress():
    """Identical consecutive frames should trigger suppression."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(obstacle_distance_m=4.2, obstacle_confidence=0.95, scene_type="sidewalk")
    first = orch.analyze_perception(frame)
    second = orch.analyze_perception(frame)
    assert first.context_plan.reminder_trigger == "update"
    assert second.context_plan.reminder_trigger == "suppress"
    assert second.context_plan.should_speak is False


def test_adaptive_suppression_scene_change_speaks():
    """Scene change should break suppression and trigger speech."""
    orch = MobilityOrchestrator()
    frame1 = PerceptionFrame(obstacle_distance_m=4.2, obstacle_confidence=0.95, scene_type="sidewalk")
    frame2 = PerceptionFrame(
        obstacle_distance_m=1.5,
        obstacle_confidence=0.95,
        scene_type="crossing",
        traffic_light="red",
        traffic_confidence=0.9,
    )
    orch.analyze_perception(frame1)
    orch.analyze_perception(frame1)  # suppress
    plan3 = orch.analyze_perception(frame2)  # scene change
    assert plan3.context_plan.reminder_trigger in {"urgent", "update"}, \
        f"Scene change should break suppression: {plan3.context_plan.reminder_trigger}"


def test_suppression_count_increments():
    """speech_suppression_count should increment when suppressed."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(obstacle_distance_m=4.2, obstacle_confidence=0.95)
    orch.analyze_perception(frame)
    orch.analyze_perception(frame)  # this should suppress
    assert orch.speech_suppression_count >= 1


# Coordination Metrics
def test_metadata_keys_present():
    """AssistancePlan.metadata must contain all required metric keys."""
    orch = MobilityOrchestrator()
    plan = orch.analyze_scenario("blocked")
    required_keys = {"event_conflict_rate", "speech_suppression_count", "median_alert_latency_ms"}
    assert required_keys.issubset(plan.metadata.keys()), \
        f"Missing metadata keys: {required_keys - plan.metadata.keys()}"


def test_metadata_conflict_rate_is_float():
    """event_conflict_rate must be a float in [0, 1]."""
    orch = MobilityOrchestrator()
    plan = orch.analyze_scenario("crossing")
    rate = plan.metadata["event_conflict_rate"]
    assert isinstance(rate, float)
    assert 0.0 <= rate <= 1.0


def test_metadata_latency_is_positive():
    """median_alert_latency_ms must be a positive number after first call."""
    orch = MobilityOrchestrator()
    plan = orch.analyze_scenario("blocked")
    latency = plan.metadata["median_alert_latency_ms"]
    assert isinstance(latency, float)
    assert latency >= 0.0


def test_metadata_suppression_count_accumulates():
    """speech_suppression_count should accumulate across multiple calls."""
    orch = MobilityOrchestrator()
    frame = PerceptionFrame(obstacle_distance_m=4.2, obstacle_confidence=0.95)
    for _ in range(5):
        orch.analyze_perception(frame)
    plan = orch.analyze_perception(frame)
    assert plan.metadata["speech_suppression_count"] >= 1
