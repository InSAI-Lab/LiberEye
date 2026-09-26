import pytest

from libereye import MobilityOrchestrator
from libereye.models import DepthEstimate, DetectedObject, PerceptionFrame, SemanticRegion, TransitCue
from libereye.scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_synthetic_scenarios_do_not_emit_study_results(scenario):
    plan = MobilityOrchestrator().analyze_scenario(scenario)

    assert plan.study_metrics == {}


def test_blocked_scenario_prioritizes_haptic_rerouting():
    plan = MobilityOrchestrator().analyze_scenario("blocked")

    assert plan.priority in {"warn", "danger"}
    assert "Tactile paving blocked" in plan.main_instruction
    assert any(cue.device == "bracelet" and cue.intensity >= 60 for cue in plan.haptics)


def test_crossing_scenario_stops_user():
    plan = MobilityOrchestrator().analyze_scenario("crossing")

    assert plan.priority == "danger"
    assert "wait" in plan.main_instruction
    assert any(cue.device == "bracelet" and cue.risk_level == "danger" for cue in plan.haptics)


def test_live_perception_with_lost_sensor_enters_failsafe():
    frame = PerceptionFrame(sensor_health="lost", obstacle_distance_m=4.0, obstacle_confidence=0.9)
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.priority == "danger"
    assert "Safety protection" in plan.main_instruction
    assert plan.haptics[0].intensity == 100


def test_low_confidence_crossing_is_conservative():
    frame = PerceptionFrame(
        traffic_light="green",
        traffic_confidence=0.9,
        user_intent="cross",
        vehicle_approaching=False,
        vehicle_confidence=0.2,
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.priority == "danger"
    assert "vehicle" in " ".join(plan.safety_notes) or any("vehicle" in result.status for result in plan.agent_results)


def test_context_plan_summarizes_risk_reasoning():
    plan = MobilityOrchestrator().analyze_scenario("crossing")

    assert plan.context_plan.reasoning_summary
    assert plan.context_plan.reminder_trigger == "urgent"
    assert plan.context_plan.should_speak is True


def test_context_plan_suppresses_redundant_low_risk_reminders():
    orchestrator = MobilityOrchestrator()
    frame = PerceptionFrame(obstacle_distance_m=4.2, obstacle_confidence=0.95)

    first = orchestrator.analyze_perception(frame)
    second = orchestrator.analyze_perception(frame)

    assert first.context_plan.reminder_trigger == "update"
    assert second.context_plan.reminder_trigger == "suppress"
    assert second.context_plan.should_speak is False


def test_clear_sidewalk_does_not_default_to_haptic_warning():
    frame = PerceptionFrame(
        scene_type="sidewalk",
        obstacle_distance_m=None,
        obstacle_confidence=0.35,
        depth_estimate=DepthEstimate(center_depth_m=4.5, left_clearance_m=4.2, right_clearance_m=4.0, confidence=0.72),
        semantic_regions=[SemanticRegion("walkable_pavement", "center", 0.24, 0.82)],
    )

    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.priority == "info"
    assert plan.haptics == []


def test_indoor_scene_does_not_trigger_crossing_haptic():
    frame = PerceptionFrame(
        scene_type="indoor",
        scene_label="Indoor office scene",
        scene_description="Indoor office scene. No obvious mobility hazard detected.",
        detected_objects=[
            DetectedObject("person", "center", 3.5, 0.8, [260, 120, 190, 280]),
            DetectedObject("keyboard", "center", 1.2, 0.8, [150, 390, 460, 80]),
            DetectedObject("monitor", "center", 2.6, 0.8, [120, 50, 520, 240]),
        ],
        semantic_regions=[
            SemanticRegion("walkable_pavement", "center", 0.42, 0.8),
            SemanticRegion("road_or_asphalt", "center", 0.18, 0.7),
        ],
    )

    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.priority == "info"
    assert plan.haptics == []
    assert "Indoor" in plan.main_instruction


def test_object_depth_spatial_audio_and_active_avoidance():
    frame = PerceptionFrame(
        detected_objects=[DetectedObject("person", "left", 1.6, 0.88, [10, 20, 80, 160])],
        depth_estimate=DepthEstimate(center_depth_m=2.1, left_clearance_m=1.5, right_clearance_m=3.6, confidence=0.86),
        obstacle_distance_m=2.1,
        obstacle_confidence=0.86,
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert any(result.agent_id == "object" for result in plan.agent_results)
    assert any(result.agent_id == "depth" for result in plan.agent_results)
    assert plan.spatial_audio
    assert plan.spatial_audio[0].direction == "left"
    assert plan.avoidance_plan.action in {"veer_right", "slow_down"}


def test_public_transit_navigation_cue():
    frame = PerceptionFrame(
        user_intent="transit",
        transit_cue=TransitCue(
            stop_name="Main Street Station",
            route_name="Bus 10",
            distance_m=12,
            direction="right",
            next_action="Approach the transit stop on the right and confirm its sign",
            confidence=0.9,
        ),
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.transit_cue is not None
    assert "Transit navigation" in plan.main_instruction
    assert any(result.agent_id == "transit" for result in plan.agent_results)
    assert any(cue.direction == "right" for cue in plan.spatial_audio)


def test_semantic_regions_prevent_veering_into_road():
    frame = PerceptionFrame(
        semantic_regions=[
            SemanticRegion("walkable_pavement", "center", 0.24, 0.82),
            SemanticRegion("road_or_asphalt", "right", 0.18, 0.8),
        ],
        depth_estimate=DepthEstimate(center_depth_m=3.8, left_clearance_m=1.4, right_clearance_m=3.9, confidence=0.86),
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert any(result.agent_id == "semantic" for result in plan.agent_results)
    assert all(result.focus.startswith("Focus: ") for result in plan.agent_results)
    assert plan.avoidance_plan.action == "slow_down"
    assert "roadway" in plan.avoidance_plan.rationale.lower()


@pytest.mark.parametrize("confidence", [0.0, 0.45, float("nan"), float("inf")])
def test_target_query_without_usable_evidence_does_not_claim_a_location(confidence):
    frame = PerceptionFrame(
        scene_type="finding", user_intent="find", target_query="cup",
        target_confidence=confidence,
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert "Target not located: cup" in plan.main_instruction
    assert "Target not located: cup" in plan.voice_message
    assert plan.haptics == []
    assert "approaching" not in " ".join(plan.context_plan.action_steps).lower()
    finding = next(result for result in plan.agent_results if result.agent_id == "finding")
    assert "nearby" not in finding.focus
    assert finding.confidence == 0.0


def test_detected_target_without_position_does_not_invent_direction_or_distance():
    frame = PerceptionFrame(
        scene_type="finding", user_intent="find", target_query="cup",
        target_confidence=0.93,
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.main_instruction == "Detected cup; position unavailable"
    assert "position unavailable" in plan.voice_message
    assert "nearby" not in plan.voice_message
    assert "m away" not in plan.voice_message
    assert plan.haptics == []


def test_observed_target_keeps_position_and_confidence_without_obstacle_cue():
    frame = PerceptionFrame(
        scene_type="finding", user_intent="find", target_query="cup",
        target_confidence=0.93, target_distance_m=2.7, target_direction="right",
    )
    plan = MobilityOrchestrator().analyze_perception(frame)

    assert plan.main_instruction == "Detected cup, on the right, about 2.7 m away"
    assert "on the right, about 2.7 m away" in plan.voice_message
    finding = next(result for result in plan.agent_results if result.agent_id == "finding")
    assert finding.confidence == 0.93
    assert plan.haptics == []


def test_target_query_defaults_to_unconfirmed_in_both_scene_input_types():
    from libereye.models import SceneState

    frame = PerceptionFrame(target_query="cup", scene_type="finding", user_intent="find")
    scene = SceneState(name="finding", description="Searching", target_query="cup", scene_type="finding", user_intent="find")
    assert frame.target_confidence == scene.target_confidence == 0.0
    for plan in [MobilityOrchestrator().analyze_perception(frame), MobilityOrchestrator().analyze_scene(scene)]:
        assert "Target not located: cup" in plan.main_instruction
        assert plan.haptics == []
