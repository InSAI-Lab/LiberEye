"""Unit tests for Event Priority Multimodal Coordination (EPMC) algorithm.

Corresponds to ICASSP 2027 paper Section 2.2, Algorithm 1, Eq. (2), and Eq. (3).
"""
from __future__ import annotations

from libereye.epmc import EPMCCoordinator, EPMCResult
from libereye.models import MobilityEvent, PerceptionFrame, SceneState
from libereye.wrist_haptics import WRIST_CUE_PRIORITY_ORDER, WRIST_CUE_PRIORITY_RANK


def test_wrist_cue_priority_ordering():
    """Verify priority ordering (Eq. 2): W3 > W2 > W1 > D4 > D3 > D2 > D1."""
    expected = ["W3", "W2", "W1", "D4", "D3", "D2", "D1"]
    assert WRIST_CUE_PRIORITY_ORDER == expected

    for i in range(len(expected) - 1):
        higher = expected[i]
        lower = expected[i + 1]
        assert WRIST_CUE_PRIORITY_RANK[higher] > WRIST_CUE_PRIORITY_RANK[lower], (
            f"Expected {higher} > {lower}"
        )


def test_algorithm1_override_selects_w3_and_retains_stop():
    """Algorithm 1 Lines 1-3: if o_t then h_t <- W3, retain stop instruction."""
    coordinator = EPMCCoordinator()
    res = coordinator.coordinate(
        candidate_cues=["D1", "D2"],
        override=True,
        override_instruction="Red-light safety override. Stop before the curb and wait",
        fused_severity="danger",
        context_change=False,
        detail_request=False,
    )

    assert res.wrist_cue == "W3"
    assert "Stop before the curb and wait" in res.action_instruction
    assert res.description_blocked is True
    assert res.description_gate is False


def test_algorithm1_selects_highest_priority_cue_when_no_override():
    """Algorithm 1 Lines 4-5: h_t <- highest-priority cue in H_t under Eq. (2)."""
    coordinator = EPMCCoordinator()

    # Mix of D2 and W2 -> W2 wins
    res = coordinator.coordinate(
        candidate_cues=["D2", "W2", "D1"],
        override=False,
        fused_severity="warn",
    )
    assert res.wrist_cue == "W2"
    assert res.preemption_occurred is True

    # Mix of D1, D3, D4 -> D4 wins
    res2 = coordinator.coordinate(
        candidate_cues=["D1", "D3", "D4"],
        override=False,
        fused_severity="warn",
    )
    assert res2.wrist_cue == "D4"
    assert res2.preemption_occurred is True


def test_algorithm1_description_block_rule_ut():
    """Eq. (3): u_t = (h_t in {W1, W2, W3, D4}) or (s_t = danger)."""
    coordinator = EPMCCoordinator()

    # Cues in {W1, W2, W3, D4} must block descriptions
    for cue in ["W1", "W2", "W3", "D4"]:
        res = coordinator.coordinate(
            candidate_cues=[cue],
            override=False,
            fused_severity="warn",
            context_change=True,
            detail_request=True,
        )
        assert res.description_blocked is True, f"Cue {cue} should set u_t = True"
        assert res.description_gate is False, f"Cue {cue} should close gate g_t"

    # Cue D1, D2, D3 with s_t != danger should NOT block descriptions (u_t = False)
    for cue in ["D1", "D2", "D3"]:
        res = coordinator.coordinate(
            candidate_cues=[cue],
            override=False,
            fused_severity="warn",
            context_change=True,
            detail_request=False,
        )
        assert res.description_blocked is False, f"Cue {cue} should not set u_t"
        assert res.description_gate is True, f"Cue {cue} with context_change should open gate g_t"


def test_algorithm1_description_admission_gate_gt():
    """Eq. (3): g_t = not u_t and (Delta_t or q_t)."""
    coordinator = EPMCCoordinator()

    # Case 1: u_t = False, Delta_t = True, q_t = False -> g_t = True
    res1 = coordinator.coordinate(
        candidate_cues=["D2"],
        override=False,
        fused_severity="info",
        context_change=True,
        detail_request=False,
    )
    assert res1.description_gate is True

    # Case 2: u_t = False, Delta_t = False, q_t = True -> g_t = True
    res2 = coordinator.coordinate(
        candidate_cues=["D2"],
        override=False,
        fused_severity="info",
        context_change=False,
        detail_request=True,
    )
    assert res2.description_gate is True

    # Case 3: u_t = False, Delta_t = False, q_t = False -> g_t = False (no change or query)
    res3 = coordinator.coordinate(
        candidate_cues=["D2"],
        override=False,
        fused_severity="info",
        context_change=False,
        detail_request=False,
    )
    assert res3.description_gate is False


def test_concise_action_instruction_remains_eligible():
    """Section 2.2 Line 10: Keep concise action instructions eligible in either case."""
    coordinator = EPMCCoordinator()

    # High risk with override: descriptions gated off, but concise action instruction eligible!
    ev = MobilityEvent(
        source_module="traffic_crossings",
        severity="danger",
        confidence=0.9,
        modalities=["wrist_haptic", "voice"],
        recommendation="Red light. Wait and do not cross",
        candidate_wrist_cue="W3",
        is_optional_description=False,
    )
    desc_ev = MobilityEvent(
        source_module="search_scene_text",
        severity="info",
        confidence=0.8,
        modalities=["voice"],
        recommendation="A convenience store is on the right and asphalt is ahead",
        candidate_wrist_cue=None,
        is_optional_description=True,
    )

    res = coordinator.coordinate(
        candidate_cues=["W3"],
        override=True,
        override_instruction="Red light. Wait and do not cross",
        fused_severity="danger",
        context_change=True,
        detail_request=True,
        events=[ev, desc_ev],
    )

    assert res.description_gate is False
    assert res.eligible_scene_description is None  # Optional description excluded
    assert "Red light. Wait" in res.action_instruction  # Concise action instruction preserved!


def test_speech_suppression_and_haptic_preemption_counts():
    """Verify speech suppression count and haptic preemption count tracking."""
    coordinator = EPMCCoordinator()
    assert coordinator.speech_suppression_count == 0
    assert coordinator.haptic_preemption_count == 0

    desc_ev = MobilityEvent(
        source_module="search_scene_text",
        severity="info",
        confidence=0.8,
        modalities=["voice"],
        recommendation="Lush vegetation on both sides of the sidewalk",
        is_optional_description=True,
    )

    # 1. Provide competing cues W1 and D2 -> haptic preemption should trigger
    coordinator.coordinate(
        candidate_cues=["D2", "W1"],
        override=False,
        fused_severity="warn",
        context_change=True,
        events=[desc_ev],
    )
    assert coordinator.haptic_preemption_count == 1
    # W1 causes u_t = True -> g_t = False -> speech suppression triggers
    assert coordinator.speech_suppression_count == 1


def test_epmc_end_to_end_analyze_scene():
    """Verify EPMCCoordinator.analyze_scene integration with scene state."""
    coordinator = EPMCCoordinator()

    # Red light crossing scene -> should select W3, danger, gate closed
    crossing_frame = PerceptionFrame(
        traffic_light="red",
        traffic_confidence=0.9,
        vehicle_approaching=True,
        vehicle_confidence=0.85,
        scene_description="Busy crossing with many pedestrians",
        scene_type="crossing",
    )
    plan = coordinator.analyze_perception(crossing_frame)

    assert plan.wrist_cue == "W3"
    assert plan.priority == "danger"
    assert plan.description_gate is False
    assert plan.description_blocked is True
    assert "wait" in plan.main_instruction or "Stop" in plan.main_instruction


def test_voice_only_action_survives_empty_candidate_set():
    event = MobilityEvent(source_module="search_scene_text", severity="info", confidence=0.9,
                          modalities=["voice"], recommendation="Confirm the stop name on arrival")
    result = EPMCCoordinator().coordinate([], events=[event])
    assert result.wrist_cue is None
    assert result.action_instruction == event.recommendation
    assert result.description_gate is False


def test_low_confidence_or_optional_event_cannot_supply_action():
    coordinator = EPMCCoordinator()
    events = [
        MobilityEvent("obstacles_tactile", "warn", 0.1, recommendation="Invalid low-confidence action", candidate_wrist_cue="D2"),
        MobilityEvent("obstacles_tactile", "warn", 0.9, recommendation="Eligible action", candidate_wrist_cue="D2"),
        MobilityEvent("search_scene_text", "info", 0.9, recommendation="Optional description", candidate_wrist_cue="D2", is_optional_description=True),
    ]
    result = coordinator.coordinate(["D2"], events=events)
    assert result.action_instruction == "Eligible action"
    assert result.eligible_scene_description is None


def test_degraded_sensor_severity_is_not_downgraded():
    plan = EPMCCoordinator().analyze_scene(SceneState("test", "test", sensor_health="degraded"))
    assert plan.priority == "warn"


def test_override_counts_displaced_plan_cues():
    result = EPMCCoordinator().coordinate(["D2"], override=True)
    assert result.preemption_occurred is True


def test_metrics_are_software_only_and_memory_is_bounded():
    coordinator = EPMCCoordinator()
    for _ in range(1030):
        plan = coordinator.analyze_scene(SceneState("test", "test"))
    assert len(coordinator.processing_latency_ms_samples) == 1024
    assert plan.metadata["physical_output_measured"] is False
    assert plan.metadata["latency_scope"] == "backend_scene_coordination_only"
    assert plan.metadata["processing_latency_ms"] >= 0
    assert plan.study_metrics == {}
    assert plan.cognitive_load == {}
