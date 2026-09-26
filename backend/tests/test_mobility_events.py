"""Unit tests for mobility events and backend perception modules.

Corresponds to ICASSP 2027 paper Section 2.1, Eq. (1) and Fig. 2.
"""
from __future__ import annotations

from libereye.models import DetectedObject, MobilityEvent, PerceptionFrame, SceneState, SemanticRegion
from libereye.mobility_events import (
    MODULE_OBSTACLE_TACTILE,
    MODULE_SEARCH_SCENE_TEXT,
    MODULE_TRAFFIC_CROSSINGS,
    distance_to_d_cue,
    extract_candidate_cues,
    fuse_severities,
)
from libereye.perception_modules import (
    BackendPerceptionPipeline,
    ObstacleTactileModule,
    SearchSceneTextModule,
    TrafficCrossingModule,
)


def test_distance_to_d_cue_mapping():
    """Verify Table 1 nominal proximity band mapping to D-level cues."""
    # 3 to 5 m -> D1
    assert distance_to_d_cue(4.5) == "D1"
    assert distance_to_d_cue(3.1) == "D1"
    # 1.5 to 3 m -> D2
    assert distance_to_d_cue(2.5) == "D2"
    assert distance_to_d_cue(1.6) == "D2"
    # 0.8 to 1.5 m -> D3
    assert distance_to_d_cue(1.2) == "D3"
    assert distance_to_d_cue(0.85) == "D3"
    # Below 0.8 m -> D4
    assert distance_to_d_cue(0.7) == "D4"
    assert distance_to_d_cue(0.3) == "D4"
    # Above 5 m -> None
    assert distance_to_d_cue(6.0) is None
    assert distance_to_d_cue(None) is None


def test_obstacle_tactile_module_emits_d_cues():
    """Verify ObstacleTactileModule emits D1-D4 events with proper source and severity."""
    module = ObstacleTactileModule()
    scene = SceneState(
        name="obstacle_test",
        description="test",
        obstacle_distance_m=1.0,
        obstacle_confidence=0.9,
    )
    events = module.process(scene)
    assert len(events) >= 1

    d3_ev = next((e for e in events if e.candidate_wrist_cue == "D3"), None)
    assert d3_ev is not None
    assert d3_ev.source_module == MODULE_OBSTACLE_TACTILE
    assert d3_ev.severity == "warn"
    assert "Nearby" in d3_ev.recommendation


def test_obstacle_tactile_module_blocked_tactile_emits_w_cues():
    """Verify blocked tactile paving emits W1 (attention) or W2 (avoidance)."""
    module = ObstacleTactileModule()
    scene = SceneState(
        name="tactile_blocked_test",
        description="test",
        tactile_blocked=True,
        tactile_confidence=0.85,
    )
    events = module.process(scene)
    tactile_ev = next((e for e in events if e.candidate_wrist_cue in {"W1", "W2"}), None)
    assert tactile_ev is not None
    assert tactile_ev.source_module == MODULE_OBSTACLE_TACTILE
    assert tactile_ev.severity == "warn"


def test_traffic_crossing_module_red_light_emits_w3_danger():
    """Verify TrafficCrossingModule emits W3 danger event on red light or vehicle."""
    module = TrafficCrossingModule()
    scene = SceneState(
        name="red_light_test",
        description="test",
        traffic_light="red",
        traffic_confidence=0.95,
        user_intent="cross",
    )
    events = module.process(scene)
    w3_ev = next((e for e in events if e.candidate_wrist_cue == "W3"), None)
    assert w3_ev is not None
    assert w3_ev.source_module == MODULE_TRAFFIC_CROSSINGS
    assert w3_ev.severity == "danger"
    assert "wait" in w3_ev.recommendation or "Red light" in w3_ev.recommendation


def test_search_scene_text_module_tags_optional_descriptions():
    """Verify SearchSceneTextModule tags scene descriptions and text reading as optional."""
    module = SearchSceneTextModule()
    scene = SceneState(
        name="scene_desc_test",
        description="Proceed along the sidewalk with vegetation on the left",
        scene_description="Proceed along the sidewalk with vegetation on the left and shop windows on the right",
        detected_texts=["Convenience store", "Subway entrance"],
    )
    events = module.process(scene)
    optional_events = [e for e in events if e.is_optional_description]
    assert len(optional_events) >= 1
    for opt_ev in optional_events:
        assert opt_ev.source_module == MODULE_SEARCH_SCENE_TEXT
        assert opt_ev.candidate_wrist_cue is None  # descriptions do not dictate wrist cues directly


def test_backend_perception_pipeline_aggregates_events():
    """Verify BackendPerceptionPipeline runs all three modules and aggregates events."""
    pipeline = BackendPerceptionPipeline()
    scene = SceneState(
        name="pipeline_test",
        description="Combined test scene",
        obstacle_distance_m=2.0,
        traffic_light="red",
        traffic_confidence=0.9,
        target_query="Subway station",
        target_distance_m=4.0,
        target_confidence=0.8,
    )
    events = pipeline.process(scene)
    modules_present = {e.source_module for e in events}
    assert MODULE_OBSTACLE_TACTILE in modules_present
    assert MODULE_TRAFFIC_CROSSINGS in modules_present
    assert MODULE_SEARCH_SCENE_TEXT in modules_present

    # Extract candidate cues
    cues = extract_candidate_cues(events)
    assert "W3" in cues  # from red light
    assert "D2" in cues  # from 2.0m obstacle


def test_invalid_distances_do_not_create_haptic_cues():
    for value in (-1.0, float("nan"), float("inf"), -float("inf")):
        assert distance_to_d_cue(value) is None
    assert distance_to_d_cue(0.8) == "D3"
    assert distance_to_d_cue(1.5) == "D3"
    assert distance_to_d_cue(3.0) == "D2"
    assert distance_to_d_cue(5.0) == "D1"


def test_candidate_gates_respect_modality_optional_flag_and_score():
    from dataclasses import replace
    event = MobilityEvent(MODULE_OBSTACLE_TACTILE, "warn", 0.55, candidate_wrist_cue="D2")
    assert extract_candidate_cues([event]) == ["D2"]
    for altered in (replace(event, confidence=0.549), replace(event, confidence=float("nan")),
                    replace(event, confidence=float("inf")), replace(event, confidence=2),
                    replace(event, modalities=["voice"]), replace(event, is_optional_description=True)):
        assert extract_candidate_cues([altered]) == []


def test_depth_does_not_borrow_confidence_from_other_evidence():
    from libereye.models import DepthEstimate
    scene = SceneState("test", "test", obstacle_distance_m=2, obstacle_confidence=0.9,
                       depth_estimate=DepthEstimate(center_depth_m=0.3, confidence=0.1))
    events = ObstacleTactileModule().process(scene)
    assert extract_candidate_cues(events) == ["D2"]
    assert events[0].confidence == 0.9


def test_low_confidence_road_region_cannot_trigger_stop():
    scene = SceneState("test", "test", semantic_regions=[SemanticRegion("road_or_asphalt", "center", 0.4, 0.1)])
    assert TrafficCrossingModule().process(scene) == []


def test_red_event_uses_red_confidence_not_unrelated_vehicle_default():
    scene = SceneState("test", "test", traffic_light="red", traffic_confidence=0.7)
    assert TrafficCrossingModule().process(scene)[0].confidence == 0.7


def test_target_event_preserves_unknown_position_in_speech():
    module = SearchSceneTextModule()
    for distance in (None, -1.0, float("nan"), float("inf")):
        scene = SceneState(
            name="finding", description="live", target_query="cup",
            target_confidence=0.9, target_distance_m=distance,
        )
        events = module.process(scene)
        target_event = next(event for event in events if event.metadata.get("target_query") == "cup")
        assert target_event.recommendation == "Found target cup; position unavailable"
        assert target_event.candidate_wrist_cue is None


def test_target_event_uses_observed_direction_without_inventing_distance():
    scene = SceneState(
        name="finding", description="live", target_query="cup",
        target_confidence=0.9, target_direction="left",
    )
    events = SearchSceneTextModule().process(scene)
    target_event = next(event for event in events if event.metadata.get("target_query") == "cup")
    assert target_event.recommendation == "Found target cup, on the left"
