from __future__ import annotations

import time
import math
from typing import List, Protocol

from .models import MobilityEvent, SceneState
from .mobility_events import (
    MODULE_OBSTACLE_TACTILE,
    MODULE_SEARCH_SCENE_TEXT,
    MODULE_TRAFFIC_CROSSINGS,
    distance_to_d_cue,
)


class PerceptionModule(Protocol):
    """Protocol for backend perception modules emitting mobility events (Section 2.1)."""
    def process(self, scene: SceneState) -> List[MobilityEvent]:
        raise NotImplementedError


class ObstacleTactileModule:
    """Obstacles and tactile paving module (Fig. 2, Section 2.1).

    Produces structured mobility events for:
    - Frontal obstacles and white cane complementary proximity (D1-D4 nominal bands)
    - Tactile paving blockage / discontinuity (W1 attention or W2 avoidance)
    - Immediate collision risk / active avoidance (W2 avoidance)
    """

    def __init__(self, confidence_gate: float = 0.55) -> None:
        self.confidence_gate = confidence_gate

    def process(self, scene: SceneState) -> List[MobilityEvent]:
        events: List[MobilityEvent] = []
        now = time.time()

        # 1. Proximity estimation from obstacle_distance_m or depth_estimate
        effective_dist = scene.obstacle_distance_m
        effective_conf = scene.obstacle_confidence

        if effective_dist is not None and (not math.isfinite(effective_dist) or effective_dist < 0):
            effective_dist = None

        if scene.depth_estimate and scene.depth_estimate.center_depth_m is not None:
            depth_dist = scene.depth_estimate.center_depth_m
            depth_conf = scene.depth_estimate.confidence
            if math.isfinite(depth_dist) and depth_dist >= 0 and depth_conf >= self.confidence_gate and (effective_dist is None or effective_conf < self.confidence_gate or depth_dist < effective_dist):
                effective_dist = depth_dist
                # Keep the confidence attached to the selected evidence.
                effective_conf = depth_conf

        if effective_dist is not None:
            d_cue = distance_to_d_cue(effective_dist)
            if d_cue is not None:
                if d_cue == "D4":
                    sev = "danger" if effective_dist < 0.5 else "warn"
                    rec = f"Very close obstacle ({effective_dist:.1f} m). Slow down or stop immediately"
                elif d_cue == "D3":
                    sev = "warn"
                    rec = f"Nearby obstacle ahead ({effective_dist:.1f} m). Slow down"
                elif d_cue == "D2":
                    sev = "warn"
                    rec = f"Medium-distance obstacle ahead ({effective_dist:.1f} m). Stay alert"
                else:  # D1
                    sev = "info"
                    rec = f"Distant obstacle ahead ({effective_dist:.1f} m). Stay alert"

                events.append(
                    MobilityEvent(
                        source_module=MODULE_OBSTACLE_TACTILE,
                        severity=sev,
                        confidence=effective_conf,
                        modalities=["bracelet", "voice"],
                        recommendation=rec,
                        candidate_wrist_cue=d_cue,
                        is_optional_description=False,
                        timestamp_s=now,
                        metadata={"distance_m": effective_dist, "cue": d_cue},
                    )
                )

        # 2. Tactile paving evaluation
        if scene.tactile_blocked and scene.tactile_confidence >= self.confidence_gate:
            # Table 1: W1 for hazard attention, W2 for avoidance request
            # Check if clearance allows avoidance
            has_avoidance_path = False
            if scene.depth_estimate and scene.depth_estimate.confidence >= self.confidence_gate and scene.depth_estimate.left_clearance_m is not None:
                has_avoidance_path = scene.depth_estimate.left_clearance_m > 1.0

            if has_avoidance_path:
                w_cue = "W2"  # Immediate avoidance request
                rec = "Tactile paving blocked. Detour one step to the left, then return to the paving"
            else:
                w_cue = "W1"  # Hazard attention
                rec = "Tactile paving may be blocked. Slow down and probe carefully"

            events.append(
                MobilityEvent(
                    source_module=MODULE_OBSTACLE_TACTILE,
                    severity="warn",
                    confidence=scene.tactile_confidence,
                    modalities=["bracelet", "voice"],
                    recommendation=rec,
                    candidate_wrist_cue=w_cue,
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"tactile_blocked": True, "cue": w_cue},
                )
            )

        # 3. Specific detected obstacles (pedestrians, bicycles, poles)
        for obj in scene.detected_objects:
            if distance_to_d_cue(obj.distance_m) in {"D3", "D4"} and obj.confidence >= self.confidence_gate:
                events.append(
                    MobilityEvent(
                        source_module=MODULE_OBSTACLE_TACTILE,
                        severity="warn",
                        confidence=obj.confidence,
                        modalities=["voice", "bracelet"],
                        recommendation=f"{obj.label} to the {obj.direction}, about {obj.distance_m:.1f} m away",
                        candidate_wrist_cue="D3" if obj.distance_m >= 0.8 else "D4",
                        is_optional_description=False,
                        timestamp_s=now,
                        metadata={"object": obj.label, "direction": obj.direction},
                    )
                )

        return events


class TrafficCrossingModule:
    """Traffic and crossings module (Fig. 2, Section 2.1).

    Produces structured mobility events for:
    - Signalized crossing status (traffic light red/yellow/green)
    - Approaching vehicles
    - Roadway/asphalt hazard and crosswalk tracking
    - Overrides for immediate traffic risk (W3 stop)
    """

    def __init__(self, confidence_gate: float = 0.65) -> None:
        self.confidence_gate = confidence_gate

    def process(self, scene: SceneState) -> List[MobilityEvent]:
        events: List[MobilityEvent] = []
        now = time.time()

        # 1. Red traffic light or approaching vehicle -> W3 Stop
        has_red = scene.traffic_light == "red" and scene.traffic_confidence >= self.confidence_gate
        has_approaching_vehicle = scene.vehicle_approaching and scene.vehicle_confidence >= self.confidence_gate

        if has_red or has_approaching_vehicle:
            reason = "Red light" if has_red and not has_approaching_vehicle else (
                "Vehicle approaching" if has_approaching_vehicle and not has_red else "Red light and approaching vehicle"
            )
            events.append(
                MobilityEvent(
                    source_module=MODULE_TRAFFIC_CROSSINGS,
                    severity="danger",
                    confidence=max([scene.traffic_confidence] if has_red and not has_approaching_vehicle else [scene.vehicle_confidence] if has_approaching_vehicle and not has_red else [scene.traffic_confidence, scene.vehicle_confidence]),
                    modalities=["bracelet", "voice"],
                    recommendation=f"{reason}. Stop before the curb and wait. Do not cross",
                    candidate_wrist_cue="W3",
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"traffic_light": scene.traffic_light, "vehicle": scene.vehicle_approaching},
                )
            )

        # 2. Roadway hazard when user has not authorized crossing
        center_roads = [
            r for r in scene.semantic_regions
            if r.label == "road_or_asphalt" and r.direction == "center" and r.coverage >= 0.14 and r.confidence >= self.confidence_gate
        ]
        if center_roads and scene.user_intent != "cross":
            events.append(
                MobilityEvent(
                    source_module=MODULE_TRAFFIC_CROSSINGS,
                    severity="danger",
                    confidence=max(region.confidence for region in center_roads),
                    modalities=["bracelet", "voice"],
                    recommendation="Roadway hazard ahead. Stop immediately and return to the sidewalk",
                    candidate_wrist_cue="W3",
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"road_hazard": True},
                )
            )

        # 3. Crossing intent with green signal
        if scene.user_intent == "cross" and scene.traffic_light == "green" and scene.traffic_confidence >= self.confidence_gate:
            events.append(
                MobilityEvent(
                    source_module=MODULE_TRAFFIC_CROSSINGS,
                    severity="info",
                    confidence=scene.traffic_confidence,
                    modalities=["voice"],
                    recommendation="Green light detected. Check vehicles and the crosswalk before deciding to cross",
                    candidate_wrist_cue=None,
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"crossing_green": True},
                )
            )
        elif scene.user_intent == "cross" and not (has_red or has_approaching_vehicle):
            events.append(
                MobilityEvent(
                    source_module=MODULE_TRAFFIC_CROSSINGS,
                    severity="warn",
                    confidence=0.75,
                    modalities=["bracelet", "voice"],
                    recommendation="Crossing area entered. Stop before the curb and check signals and vehicles",
                    candidate_wrist_cue="W1",
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"approaching_crossing": True},
                )
            )

        return events


class SearchSceneTextModule:
    """Target search, scene description, and text reading module (Fig. 2, Section 2.1).

    Produces structured mobility events for:
    - Target search (e.g., finding store entrance, bus stop, landmark)
    - Panoramic scene description (optional scene detail, subject to EPMC gate g_t)
    - Text reading (street signs, storefront signboards, transit info)
    """

    def __init__(self, confidence_gate: float = 0.50) -> None:
        self.confidence_gate = confidence_gate

    def process(self, scene: SceneState) -> List[MobilityEvent]:
        events: List[MobilityEvent] = []
        now = time.time()

        # 1. Target search
        if scene.target_query and self.confidence_gate <= scene.target_confidence <= 1.0:
            details = []
            direction_text = {"left": "on the left", "center": "ahead", "right": "on the right"}.get(scene.target_direction)
            if direction_text:
                details.append(direction_text)
            distance = scene.target_distance_m
            if distance is not None and math.isfinite(distance) and distance > 0:
                details.append(f"about {distance:.1f} m away")
            location = f", {', '.join(details)}" if details else "; position unavailable"
            events.append(
                MobilityEvent(
                    source_module=MODULE_SEARCH_SCENE_TEXT,
                    severity="info",
                    confidence=scene.target_confidence,
                    modalities=["voice"],
                    recommendation=f"Found target {scene.target_query}{location}",
                    # Target distance alone is not obstacle proximity.
                    candidate_wrist_cue=None,
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"target_query": scene.target_query, "direction": scene.target_direction},
                )
            )

        # 2. Transit cue
        if scene.transit_cue and scene.transit_cue.stop_name and scene.user_intent == "transit":
            events.append(
                MobilityEvent(
                    source_module=MODULE_SEARCH_SCENE_TEXT,
                    severity="info",
                    confidence=scene.transit_cue.confidence,
                    modalities=["voice"],
                    recommendation=scene.transit_cue.next_action or f"Transit stop: {scene.transit_cue.stop_name}",
                    candidate_wrist_cue=None,
                    is_optional_description=False,
                    timestamp_s=now,
                    metadata={"transit": scene.transit_cue.stop_name},
                )
            )

        # 3. Optional scene description, subject to gate g_t.
        # Section 2.2: 'A true g_t makes an optional scene description eligible, while a false g_t withholds it.'
        if scene.scene_description:
            events.append(
                MobilityEvent(
                    source_module=MODULE_SEARCH_SCENE_TEXT,
                    severity="info",
                    confidence=0.85,
                    modalities=["voice"],
                    recommendation=scene.scene_description,
                    candidate_wrist_cue=None,
                    is_optional_description=True,  # Gated by g_t
                    timestamp_s=now,
                    metadata={"type": "scene_description"},
                )
            )
        elif scene.description and scene.description != "live":
            events.append(
                MobilityEvent(
                    source_module=MODULE_SEARCH_SCENE_TEXT,
                    severity="info",
                    confidence=0.80,
                    modalities=["voice"],
                    recommendation=scene.description,
                    candidate_wrist_cue=None,
                    is_optional_description=True,  # Gated by g_t
                    timestamp_s=now,
                    metadata={"type": "scene_description"},
                )
            )

        # 4. Text reading and signboards, subject to gate g_t.
        all_texts = list(scene.detected_texts) + list(scene.sign_candidates)
        if all_texts:
            text_str = ", ".join(all_texts[:3])
            events.append(
                MobilityEvent(
                    source_module=MODULE_SEARCH_SCENE_TEXT,
                    severity="info",
                    confidence=0.75,
                    modalities=["voice"],
                    recommendation=f"Recognized sign text: {text_str}",
                    candidate_wrist_cue=None,
                    is_optional_description=True,  # Gated by g_t
                    timestamp_s=now,
                    metadata={"texts": all_texts},
                )
            )

        return events


class BackendPerceptionPipeline:
    """Coordinates the three backend perception modules (Fig. 2, Section 2.1)."""

    def __init__(self) -> None:
        self.obstacle_module = ObstacleTactileModule()
        self.traffic_module = TrafficCrossingModule()
        self.search_module = SearchSceneTextModule()

    def process(self, scene: SceneState) -> List[MobilityEvent]:
        events: List[MobilityEvent] = []
        events.extend(self.obstacle_module.process(scene))
        events.extend(self.traffic_module.process(scene))
        events.extend(self.search_module.process(scene))
        return events
