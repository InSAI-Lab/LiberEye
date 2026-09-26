from __future__ import annotations

from abc import ABC, abstractmethod
import math

from .models import AgentResult, SceneState


REGION_LABELS = {
    "vegetation": "vegetation area",
    "tactile_paving": "tactile paving",
    "crosswalk": "crosswalk",
    "road_or_asphalt": "roadway or asphalt area",
    "walkable_pavement": "walkable pavement",
}

DIRECTION_LABELS = {"left": "on the left", "center": "ahead", "right": "on the right", "unknown": "nearby"}


class Agent(ABC):
    agent_id: str
    agent_name: str

    @abstractmethod
    def analyze(self, scene: SceneState) -> AgentResult:
        raise NotImplementedError


class ObstacleAgent(Agent):
    agent_id = "obstacle"
    agent_name = "Obstacle avoidance specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        distance = scene.obstacle_distance_m
        if distance is not None and scene.obstacle_confidence < 0.5:
            return AgentResult(self.agent_id, self.agent_name, "Possible obstacle with insufficient confidence", "info", scene.obstacle_confidence, "Capture the next frame for confirmation", ["phone"])
        if distance is not None and distance <= 1.5 and scene.obstacle_confidence >= 0.65:
            return AgentResult(self.agent_id, self.agent_name, f"Obstacle {distance:.1f} m away", "danger", scene.obstacle_confidence, "Stop and confirm the avoidance direction", ["bracelet", "voice"])
        if distance is not None and distance <= 2.5 and scene.obstacle_confidence >= 0.55:
            return AgentResult(self.agent_id, self.agent_name, f"Object {distance:.1f} m ahead with space to go around it", "warn", scene.obstacle_confidence, "Keep a slow pace and check lateral space", ["bracelet"])
        return AgentResult(self.agent_id, self.agent_name, "Nearby path clear", "info", 0.86, "Continue forward", ["phone"])


class TactilePavingAgent(Agent):
    agent_id = "tactile"
    agent_name = "Tactile paving specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.tactile_confidence < 0.45:
            return AgentResult(self.agent_id, self.agent_name, "Insufficient tactile paving confidence", "warn", scene.tactile_confidence, "Slow down and check the path underfoot", ["bracelet", "voice"])
        if scene.tactile_blocked:
            return AgentResult(self.agent_id, self.agent_name, "Tactile paving partly blocked", "warn", 0.88, "Step left around the obstruction, then return to the tactile paving", ["bracelet"])
        return AgentResult(self.agent_id, self.agent_name, "Tactile paving is continuous", "info", 0.9, "Continue along the tactile paving", ["bracelet"])


class ObjectDetectionAgent(Agent):
    agent_id = "object"
    agent_name = "Object detection specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        objects = sorted(
            scene.detected_objects,
            key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
        )
        if not objects:
            return AgentResult(self.agent_id, self.agent_name, "No relevant object detected", "info", 0.58, "Continue using depth and tactile paving cues", ["phone"])

        nearest = objects[0]
        distance_text = f"{nearest.distance_m:.1f} m" if nearest.distance_m is not None else "distance unknown"
        status = f"{nearest.label} detected to the {nearest.direction}, {distance_text}"
        if scene.scene_type == "indoor":
            labels = ", ".join(obj.label for obj in objects[:3])
            return AgentResult(self.agent_id, self.agent_name, f"Indoor objects: {labels}", "info", min(0.9, nearest.confidence), "Provide a scene description without a movement alert", ["phone", "voice"])
        if nearest.confidence < 0.5:
            return AgentResult(self.agent_id, self.agent_name, status, "info", nearest.confidence, "Object detection confidence is low. Wait for the next frame", ["phone"])
        if nearest.distance_m is not None and nearest.distance_m <= 1.5 and nearest.confidence >= 0.65:
            return AgentResult(self.agent_id, self.agent_name, status, "danger", nearest.confidence, "Stop or go around the nearest object", ["bracelet", "voice"])
        if nearest.distance_m is not None and nearest.distance_m <= 2.5 and nearest.confidence >= 0.55:
            return AgentResult(self.agent_id, self.agent_name, status, "warn", nearest.confidence, "Slow down and maintain lateral clearance", ["bracelet", "voice"])
        return AgentResult(self.agent_id, self.agent_name, status, "info", nearest.confidence, "Maintain the current direction and keep observing", ["phone"])


class DepthEstimationAgent(Agent):
    agent_id = "depth"
    agent_name = "Depth estimation specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        depth = scene.depth_estimate
        if depth is None:
            return AgentResult(self.agent_id, self.agent_name, "No depth estimate received", "info", 0.55, "Use monocular heuristic distance cues", ["phone"])
        if depth.confidence < 0.45:
            return AgentResult(self.agent_id, self.agent_name, "Insufficient depth estimation confidence", "warn", depth.confidence, "Slow down and request the next frame for confirmation", ["bracelet", "voice"])
        center = depth.center_depth_m
        if center is not None and center <= 1.3 and depth.confidence >= 0.65:
            return AgentResult(self.agent_id, self.agent_name, f"Center depth ahead: about {center:.1f} m", "danger", depth.confidence, "Stop immediately and replan", ["bracelet", "voice"])
        if center is not None and center <= 2.2 and depth.confidence >= 0.58:
            return AgentResult(self.agent_id, self.agent_name, f"Center depth ahead: about {center:.1f} m", "warn", depth.confidence, "Slow down and look for more open space", ["bracelet", "voice"])
        return AgentResult(self.agent_id, self.agent_name, "Sufficient depth clearance ahead", "info", depth.confidence, "Continue forward", ["phone"])


class SemanticSegmentationAgent(Agent):
    agent_id = "semantic"
    agent_name = "Semantic segmentation specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if not scene.semantic_regions:
            return AgentResult(self.agent_id, self.agent_name, "No walkable-area segmentation received", "info", 0.48, "Continue using depth, tactile paving and object detection cues", ["phone"])

        center_road = _best_region(scene, "road_or_asphalt", "center")
        center_vegetation = _best_region(scene, "vegetation", "center")
        walkable = _best_region(scene, "walkable_pavement") or _best_region(scene, "tactile_paving")
        right_road = _best_region(scene, "road_or_asphalt", "right")

        if center_road and _dominant_center_road(scene, min_coverage=0.08) and scene.user_intent != "cross":
            return AgentResult(self.agent_id, self.agent_name, "Roadway hazard directly ahead", "danger", center_road.confidence, "Stop and check whether you have left the sidewalk", ["bracelet", "voice"])
        if center_vegetation and center_vegetation.coverage > 0.1:
            return AgentResult(self.agent_id, self.agent_name, "Vegetation or non-walkable area directly ahead", "warn", center_vegetation.confidence, "Slow down and return to paved ground", ["bracelet", "voice"])
        if walkable:
            direction = DIRECTION_LABELS[walkable.direction]
            label = REGION_LABELS.get(walkable.label, walkable.label)
            if right_road:
                return AgentResult(self.agent_id, self.agent_name, f"{label} detected {direction}, with a roadway boundary on the right", "info", walkable.confidence, "Continue along the walkable area and avoid drifting right", ["voice", "phone"])
            return AgentResult(self.agent_id, self.agent_name, f"{label} detected {direction}", "info", walkable.confidence, "Continue along the walkable area", ["phone"])
        labels = ", ".join(REGION_LABELS.get(region.label, region.label) for region in scene.semantic_regions[:3])
        return AgentResult(self.agent_id, self.agent_name, f"Detected regions: {labels}", "warn", 0.58, "Slow down and confirm the walkable area", ["bracelet", "voice"])


class RouteAgent(Agent):
    agent_id = "route"
    agent_name = "Safe path specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.sensor_health == "lost":
            return AgentResult(self.agent_id, self.agent_name, "Critical sensor disconnected", "danger", 1.0, "Stop and wait for human confirmation", ["bracelet", "voice"])
        center_road = _best_region(scene, "road_or_asphalt", "center")
        if center_road and _dominant_center_road(scene, min_coverage=0.08) and scene.user_intent != "cross":
            return AgentResult(self.agent_id, self.agent_name, "Path center enters a roadway hazard area", "danger", center_road.confidence, "Stop and return to the sidewalk or tactile paving", ["bracelet", "voice"])
        if scene.vehicle_approaching or scene.traffic_light == "red":
            return AgentResult(self.agent_id, self.agent_name, "Current path enters a high-risk area", "danger", 0.87, "Stop before the curb and wait", ["bracelet", "voice"])
        if scene.tactile_blocked:
            return AgentResult(self.agent_id, self.agent_name, "Short-distance replanning needed", "warn", 0.84, "Turn left 25 degrees and detour 2 m", ["bracelet"])
        right_road = _best_region(scene, "road_or_asphalt", "right")
        if right_road and right_road.coverage > 0.08 and (_best_region(scene, "walkable_pavement") or _best_region(scene, "tactile_paving")):
            return AgentResult(self.agent_id, self.agent_name, "Roadway boundary detected on the right", "info", 0.82, "Continue along the inner sidewalk", ["bracelet"])
        return AgentResult(self.agent_id, self.agent_name, "Right boundary is safe", "info", 0.8, "Maintain the current route", ["bracelet"])


class ActiveAvoidanceAgent(Agent):
    agent_id = "avoidance"
    agent_name = "Active avoidance specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        depth = scene.depth_estimate
        left_clearance = depth.left_clearance_m if depth else None
        right_clearance = depth.right_clearance_m if depth else None
        distance = scene.obstacle_distance_m

        if distance is not None and distance <= 1.5:
            return AgentResult(self.agent_id, self.agent_name, "Insufficient safe clearance ahead", "danger", scene.obstacle_confidence, "Stop and wait for confirmation", ["bracelet", "voice"])
        if left_clearance is not None and right_clearance is not None:
            right_road = _best_region(scene, "road_or_asphalt", "right")
            left_road = _best_region(scene, "road_or_asphalt", "left")
            right_is_road = right_road is not None and right_road.coverage > 0.08
            left_is_road = left_road is not None and left_road.coverage > 0.08
            if left_clearance - right_clearance > 0.8:
                if left_is_road:
                    return AgentResult(self.agent_id, self.agent_name, "Space on the left is open but includes a roadway hazard", "warn", depth.confidence, "Do not drift left. Stay on walkable pavement", ["bracelet", "voice"])
                return AgentResult(self.agent_id, self.agent_name, "More open space on the left", "warn", depth.confidence, "Take a small detour to the left", ["bracelet", "voice"])
            if right_clearance - left_clearance > 0.8:
                if right_is_road:
                    return AgentResult(self.agent_id, self.agent_name, "Space on the right is open but includes a roadway hazard", "warn", depth.confidence, "Do not drift right. Stay on the inner sidewalk", ["bracelet", "voice"])
                return AgentResult(self.agent_id, self.agent_name, "More open space on the right", "warn", depth.confidence, "Take a small detour to the right", ["bracelet", "voice"])
        if scene.tactile_blocked:
            return AgentResult(self.agent_id, self.agent_name, "Detour needed near the tactile paving", "warn", 0.82, "Take a short detour and return to the tactile paving", ["bracelet", "voice"])
        return AgentResult(self.agent_id, self.agent_name, "No active detour needed", "info", 0.72, "Maintain the current route", ["phone"])


class TrafficLightAgent(Agent):
    agent_id = "traffic"
    agent_name = "Traffic light specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.traffic_light != "unknown" and scene.traffic_confidence < 0.55:
            return AgentResult(self.agent_id, self.agent_name, "Traffic light recognition is unreliable", "warn", scene.traffic_confidence, "Do not enter the crossing. Wait for confirmation", ["bracelet", "voice"])
        if scene.traffic_light == "red":
            return AgentResult(self.agent_id, self.agent_name, "Red light", "danger", 0.93, "Stop and wait", ["bracelet", "voice"])
        if scene.traffic_light == "green":
            return AgentResult(self.agent_id, self.agent_name, "Green light", "info", 0.89, "Check vehicles before proceeding", ["phone"])
        if scene.traffic_light == "yellow":
            return AgentResult(self.agent_id, self.agent_name, "Yellow light", "warn", 0.81, "Do not enter the crossing", ["bracelet", "voice"])
        return AgentResult(self.agent_id, self.agent_name, "No traffic light detected", "info", 0.62, "Continue the current task", ["phone"])


class CrossingAgent(Agent):
    agent_id = "crossing"
    agent_name = "Crossing specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.user_intent == "cross" and scene.vehicle_confidence < 0.55:
            return AgentResult(self.agent_id, self.agent_name, "Vehicle motion assessment is unreliable", "danger", scene.vehicle_confidence, "Stop and wait for a second confirmation", ["bracelet", "voice"])
        if scene.user_intent == "cross" and scene.vehicle_approaching:
            return AgentResult(self.agent_id, self.agent_name, "Vehicle approaching", "danger", 0.9, "Stop and wait for a second confirmation", ["bracelet", "voice"])
        if scene.user_intent == "cross":
            return AgentResult(self.agent_id, self.agent_name, "Crosswalk area available for inspection", "warn", 0.76, "Approach the curb slowly", ["bracelet"])
        return AgentResult(self.agent_id, self.agent_name, "No crossing task active", "info", 0.72, "Crossing specialist on standby", ["phone"])


class SpatialAudioAgent(Agent):
    agent_id = "spatial_audio"
    agent_name = "Spatial audio specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        nearest = min(
            scene.detected_objects,
            key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
            default=None,
        )
        if nearest and nearest.distance_m is not None and nearest.distance_m <= 3.0:
            return AgentResult(
                self.agent_id,
                self.agent_name,
                f"Spatial audio cue needed to the {nearest.direction}: {nearest.label}",
                "warn" if nearest.distance_m > 1.5 else "danger",
                nearest.confidence,
                "Use left/right audio positioning to indicate the hazard source",
                ["voice", "phone"],
            )
        if scene.transit_cue and scene.transit_cue.direction != "unknown":
            return AgentResult(self.agent_id, self.agent_name, f"Transit destination to the {scene.transit_cue.direction}", "info", scene.transit_cue.confidence, "Use spatial audio to indicate the stop direction", ["voice", "phone"])
        return AgentResult(self.agent_id, self.agent_name, "No spatial audio cue available", "info", 0.6, "Keep standard speech mode", ["phone"])


class FindingAgent(Agent):
    agent_id = "finding"
    agent_name = "Object search specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if not scene.target_query:
            return AgentResult(self.agent_id, self.agent_name, "No object search request received", "info", 0.78, "Continue navigation", ["phone"])
        if not 0.5 <= scene.target_confidence <= 1.0:
            message = f"Target not located: {scene.target_query}"
            return AgentResult(self.agent_id, self.agent_name, message, "info", 0.0, f"{message}. Capture another view to continue searching", ["voice", "phone"])

        details = []
        direction = {"left": "on the left", "center": "ahead", "right": "on the right"}.get(scene.target_direction)
        if direction:
            details.append(direction)
        distance = scene.target_distance_m
        if distance is not None and math.isfinite(distance) and distance > 0:
            details.append(f"about {distance:.1f} m away")
        status = f"Detected {scene.target_query}"
        status += f", {', '.join(details)}" if details else "; position unavailable"
        return AgentResult(self.agent_id, self.agent_name, status, "info", scene.target_confidence, f"{status}. Confirm the target position and path before moving", ["voice", "phone"])


class TransitNavigationAgent(Agent):
    agent_id = "transit"
    agent_name = "Public transit specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        cue = scene.transit_cue
        if cue is None or not cue.stop_name:
            return AgentResult(self.agent_id, self.agent_name, "No transit destination set", "info", 0.55, "Public transit navigation on standby", ["phone"])

        route = f"{cue.route_name} " if cue.route_name else ""
        distance = f"{cue.distance_m:.0f} m" if cue.distance_m is not None else "distance unknown"
        status = f"{route}{cue.stop_name} to the {cue.direction}, about {distance}"
        if cue.distance_m is not None and cue.distance_m <= 15:
            return AgentResult(self.agent_id, self.agent_name, status, "warn", cue.confidence, cue.next_action or "Approach the stop and confirm the stop sign", ["voice", "phone"])
        return AgentResult(self.agent_id, self.agent_name, status, "info", cue.confidence, cue.next_action or "Follow a safe path to the transit stop", ["voice", "phone"])


class SceneDescriptionAgent(Agent):
    agent_id = "scene"
    agent_name = "Scene description specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        severity = "warn" if scene.crowd_level == "high" or scene.tactile_blocked else "info"
        return AgentResult(self.agent_id, self.agent_name, scene.description, severity, 0.85, "Provide a brief scene summary on request", ["voice", "phone"])


class TextRecognitionAgent(Agent):
    agent_id = "text"
    agent_name = "Text recognition specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.detected_texts:
            text = ", ".join(scene.detected_texts[:3])
            return AgentResult(self.agent_id, self.agent_name, f"Recognized text: {text}", "info", 0.72, "Read the text on request", ["voice", "phone"])
        return AgentResult(self.agent_id, self.agent_name, "No reliable text recognized", "info", 0.55, "Text recognition on standby", ["phone"])


class SignRecognitionAgent(Agent):
    agent_id = "sign"
    agent_name = "Storefront sign specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        if scene.sign_candidates:
            signs = ", ".join(scene.sign_candidates[:2])
            return AgentResult(self.agent_id, self.agent_name, f"Sign candidates: {signs}", "info", 0.68, "Describe nearby storefronts or entrances", ["voice", "phone"])
        if scene.detected_texts:
            return AgentResult(self.agent_id, self.agent_name, "Text recognized, but no sign confirmed", "info", 0.58, "Move closer and recognize again", ["phone"])
        return AgentResult(self.agent_id, self.agent_name, "No sign candidates found", "info", 0.55, "Sign recognition on standby", ["phone"])


class IntentAgent(Agent):
    agent_id = "intent"
    agent_name = "Intent recognition specialist"

    def analyze(self, scene: SceneState) -> AgentResult:
        labels = {
            "navigate": "Navigation intent",
            "cross": "Crossing intent",
            "find": "Object search intent",
            "chat": "Casual conversation intent",
            "transit": "Transit navigation intent",
        }
        severity = "warn" if scene.user_intent in {"cross", "find", "transit"} else "info"
        return AgentResult(self.agent_id, self.agent_name, labels[scene.user_intent], severity, 0.8, "Adjust feedback priority to match the intent", ["phone"])


def _best_region(scene: SceneState, label: str, direction: str | None = None):
    candidates = [
        region
        for region in scene.semantic_regions
        if region.label == label and (direction is None or region.direction == direction)
    ]
    return max(candidates, key=lambda region: region.coverage, default=None)


def _dominant_center_road(scene: SceneState, min_coverage: float = 0.08) -> bool:
    road = _best_region(scene, "road_or_asphalt", "center")
    if not road or road.coverage <= min_coverage:
        return False
    walkable_coverage = sum(
        region.coverage
        for region in scene.semantic_regions
        if region.label in {"walkable_pavement", "tactile_paving"}
    )
    tactile_coverage = sum(region.coverage for region in scene.semantic_regions if region.label == "tactile_paving")
    if tactile_coverage > 0.015 and road.coverage > min_coverage:
        return True
    return road.coverage > max(min_coverage, walkable_coverage * 1.15)


DEFAULT_AGENTS = [
    ObstacleAgent(),
    TactilePavingAgent(),
    ObjectDetectionAgent(),
    DepthEstimationAgent(),
    SemanticSegmentationAgent(),
    RouteAgent(),
    ActiveAvoidanceAgent(),
    TrafficLightAgent(),
    CrossingAgent(),
    SpatialAudioAgent(),
    FindingAgent(),
    TransitNavigationAgent(),
    SceneDescriptionAgent(),
    TextRecognitionAgent(),
    SignRecognitionAgent(),
    IntentAgent(),
]
