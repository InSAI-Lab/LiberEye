from __future__ import annotations

from .models import PerceptionFrame, SceneState


class SceneAdapter:
    """Converts normalized perception output into the agent-facing scene state."""

    def from_perception(self, frame: PerceptionFrame, name: str = "live") -> SceneState:
        scene_name = frame.scene_type if frame.scene_type != "unknown" else name
        description = frame.scene_description or self._describe(frame)
        return SceneState(
            name=scene_name,
            description=description,
            obstacle_distance_m=frame.obstacle_distance_m,
            obstacle_confidence=frame.obstacle_confidence,
            tactile_blocked=frame.tactile_blocked,
            tactile_confidence=frame.tactile_confidence,
            traffic_light=frame.traffic_light,
            traffic_confidence=frame.traffic_confidence,
            vehicle_approaching=frame.vehicle_approaching,
            vehicle_confidence=frame.vehicle_confidence,
            target_query=frame.target_query,
            target_distance_m=frame.target_distance_m,
            target_direction=frame.target_direction,
            target_confidence=frame.target_confidence,
            crowd_level=frame.crowd_level,
            user_intent=frame.user_intent,
            scene_type=frame.scene_type,
            scene_label=frame.scene_label,
            detected_objects=frame.detected_objects,
            semantic_regions=frame.semantic_regions,
            depth_estimate=frame.depth_estimate,
            transit_cue=frame.transit_cue,
            detected_texts=frame.detected_texts,
            sign_candidates=frame.sign_candidates,
            scene_description=frame.scene_description,
            sensor_health=frame.sensor_health,
            timestamp_s=frame.timestamp_s,
        )

    def _describe(self, frame: PerceptionFrame) -> str:
        parts: list[str] = []
        if frame.obstacle_distance_m is not None:
            parts.append(f"Obstacle about {frame.obstacle_distance_m:.1f} m ahead")
        if frame.tactile_blocked:
            parts.append("Tactile paving may be blocked")
        if frame.traffic_light != "unknown":
            parts.append(f"Traffic light: {frame.traffic_light}")
        if frame.vehicle_approaching:
            parts.append("Approaching vehicle detected")
        if frame.target_query:
            parts.append(f"Searching for {frame.target_query}")
        if frame.detected_objects:
            parts.append("Detected objects: " + ", ".join(obj.label for obj in frame.detected_objects[:3]))
        if frame.semantic_regions:
            region_text = ", ".join(self._region_label(region.label) for region in frame.semantic_regions[:4])
            parts.append("Scene regions: " + region_text)
        if frame.depth_estimate and frame.depth_estimate.center_depth_m is not None:
            parts.append(f"Center depth ahead: about {frame.depth_estimate.center_depth_m:.1f} m")
        if frame.transit_cue and frame.transit_cue.stop_name:
            parts.append(f"Transit destination: {frame.transit_cue.stop_name}")
        if frame.sign_candidates:
            parts.append("Sign candidates: " + ", ".join(frame.sign_candidates[:2]))
        if frame.detected_texts:
            parts.append("Recognized text: " + ", ".join(frame.detected_texts[:2]))
        if not parts:
            parts.append("No clear risk detected in the current frame")
        return ", ".join(parts) + "."

    def _region_label(self, label: str) -> str:
        labels = {
            "vegetation": "vegetation",
            "tactile_paving": "tactile paving",
            "crosswalk": "crosswalk",
            "road_or_asphalt": "roadway or asphalt area",
            "walkable_pavement": "walkable pavement",
            "indoor": "indoor area",
            "street": "Roadside",
        }
        return labels.get(label, label)
