from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from .models import AgentResult, ContextPlan, HapticCue, SceneState, Severity


SEVERITY_RANK = {"info": 0, "warn": 1, "danger": 2}

# Obstacle distance buckets for risk_signature
def _distance_bucket(distance_m: float | None) -> str:
    if distance_m is None:
        return "none"
    if distance_m < 1.0:
        return "<1m"
    if distance_m < 3.0:
        return "1-3m"
    return ">3m"


@dataclass(frozen=True)
class ReminderMemory:
    timestamp_s: float
    priority: Severity
    instruction: str
    risk_signature: tuple[str, ...]
    haptic_intensity: int


class MobilityContextPlanner:
    """Summarize mobility context and suppress redundant feedback.

    Scene context, dynamic risks and action steps are evaluated across nearby
    frames. The suppression window decreases when at least two risk fields
    change and increases when the scene remains stable.
    """

    BASE_SUPPRESS_WINDOW_S = 3.0
    MIN_SUPPRESS_WINDOW_S = 0.5
    MAX_SUPPRESS_WINDOW_S = 8.0

    def __init__(self, history_size: int = 8, suppress_window_s: float = 3.0) -> None:
        self.history: deque[ReminderMemory] = deque(maxlen=history_size)
        self.suppress_window_s = suppress_window_s  # kept for backward compat

    def _adaptive_suppress_window(self, risk_signature: tuple[str, ...]) -> float:
        """Compute adaptive suppression window based on change rate."""
        if not self.history:
            return self.BASE_SUPPRESS_WINDOW_S
        last_sig = self.history[-1].risk_signature
        # Count differing fields between consecutive risk_signatures
        change_rate = sum(1 for a, b in zip(risk_signature, last_sig) if a != b)
        # High change rate → lower suppression (speak more)
        # Stable → higher suppression (speak less)
        if change_rate >= 2:
            return self.MIN_SUPPRESS_WINDOW_S
        elif change_rate == 1:
            return self.BASE_SUPPRESS_WINDOW_S
        else:
            return self.MAX_SUPPRESS_WINDOW_S

    def plan(
        self,
        scene: SceneState,
        results: list[AgentResult],
        priority: Severity,
        main_instruction: str,
        haptics: list[HapticCue],
        safety_notes: list[str],
    ) -> ContextPlan:
        static_context = self._static_context(scene)
        dynamic_risks = self._dynamic_risks(scene, results, safety_notes)
        action_steps = self._action_steps(priority, main_instruction, scene, dynamic_risks)
        # risk_signature uses 4-tuple with distance bucket
        risk_signature = (
            scene.scene_type,
            _distance_bucket(scene.obstacle_distance_m),
            scene.traffic_light,
            str(scene.tactile_blocked),
        )
        haptic_intensity = haptics[0].intensity if haptics else 0
        # adaptive suppression window
        adaptive_window = self._adaptive_suppress_window(risk_signature)
        trigger, reason = self._trigger_state(priority, main_instruction, risk_signature, haptic_intensity, adaptive_window)
        should_speak = trigger in {"urgent", "update"}
        reasoning_summary = self._reasoning_summary(priority, dynamic_risks, action_steps, trigger)

        self.history.append(
            ReminderMemory(
                timestamp_s=time.time(),
                priority=priority,
                instruction=main_instruction,
                risk_signature=risk_signature,
                haptic_intensity=haptic_intensity,
            )
        )

        return ContextPlan(
            static_context=static_context,
            dynamic_risks=dynamic_risks,
            action_steps=action_steps,
            reasoning_summary=reasoning_summary,
            reminder_trigger=trigger,
            should_speak=should_speak,
            redundancy_reason=reason,
        )

    def _static_context(self, scene: SceneState) -> list[str]:
        context = [scene.description]
        if scene.traffic_light != "unknown":
            context.append(f"Traffic light: {scene.traffic_light}")
        if scene.crowd_level != "low":
            context.append(f"Environment complexity: {scene.crowd_level}")
        if scene.semantic_regions:
            context.append("Semantic regions: " + ", ".join(self._region_text(region.label, region.direction) for region in scene.semantic_regions[:4]))
        if scene.detected_texts:
            context.append("Readable text: " + ", ".join(scene.detected_texts[:3]))
        if scene.sign_candidates:
            context.append("Sign candidates: " + ", ".join(scene.sign_candidates[:3]))
        if scene.target_query:
            context.append(f"Current task: find {scene.target_query}")
        if scene.transit_cue and scene.transit_cue.stop_name:
            context.append(f"Transit destination: {scene.transit_cue.stop_name}")
        return context

    def _dynamic_risks(self, scene: SceneState, results: list[AgentResult], safety_notes: list[str]) -> list[str]:
        risks: list[str] = []
        if scene.sensor_health != "ok":
            risks.append(f"Sensor status: {scene.sensor_health}")
        if scene.obstacle_distance_m is not None and scene.obstacle_distance_m <= 3.0:
            risks.append(f"Nearby obstacle: {scene.obstacle_distance_m:.1f} m")
        if scene.depth_estimate and scene.depth_estimate.center_depth_m is not None and scene.depth_estimate.center_depth_m <= 2.8:
            risks.append(f"Center depth: {scene.depth_estimate.center_depth_m:.1f} m")
        for obj in scene.detected_objects[:3]:
            if obj.distance_m is not None and obj.distance_m <= 3.0:
                risks.append(f"{obj.label} to the {obj.direction}: {obj.distance_m:.1f} m")
        for region in scene.semantic_regions:
            if region.label == "road_or_asphalt" and region.direction == "center" and region.coverage > 0.08:
                risks.append("Roadway hazard directly ahead")
            elif region.label == "road_or_asphalt" and region.direction == "right" and region.coverage > 0.08:
                risks.append("Roadway boundary on the right")
            elif region.label == "vegetation" and region.direction == "center" and region.coverage > 0.1:
                risks.append("Vegetation directly ahead is not walkable")
        if scene.tactile_blocked:
            risks.append("Tactile paving blocked")
        if scene.traffic_light == "red":
            risks.append("Red light")
        if scene.vehicle_approaching:
            risks.append("Vehicle approaching")
        for note in safety_notes:
            risks.append(note)

        severe_results = [result for result in results if result.severity in {"danger", "warn"}]
        for result in severe_results[:3]:
            label = f"{result.agent_name}:{result.status}"
            if label not in risks:
                risks.append(label)
        return risks or ["No clear dynamic hazard detected"]

    def _action_steps(self, priority: Severity, main_instruction: str, scene: SceneState, risks: list[str]) -> list[str]:
        if priority == "danger":
            return ["Stop immediately", "Stay in place", "Wait for environmental or human confirmation"]
        if scene.tactile_blocked:
            return ["Slow down", "Avoid the obstruction on the tactile paving", "Return to a verified path"]
        if scene.target_query:
            return ["Confirm the target position", main_instruction, "Check the path before moving"]
        if risks == ["No clear dynamic hazard detected"]:
            return ["Continue in the current direction", "Keep listening to the surroundings", "Wait for the next perception update"]
        return ["Slow down and observe", main_instruction, "Reconfirm the path if needed"]

    def _trigger_state(
        self,
        priority: Severity,
        instruction: str,
        risk_signature: tuple[str, ...],
        haptic_intensity: int,
        adaptive_window: float,
    ) -> tuple[str, str | None]:
        if priority == "danger" or haptic_intensity >= 90:
            return "urgent", None

        now = time.time()
        if not self.history:
            return "update", None

        last = self.history[-1]
        same_message = last.instruction == instruction and last.risk_signature == risk_signature
        same_or_lower_priority = SEVERITY_RANK[priority] <= SEVERITY_RANK[last.priority]
        close_in_time = now - last.timestamp_s < adaptive_window
        similar_haptic = abs(haptic_intensity - last.haptic_intensity) < 10

        if same_message and same_or_lower_priority and close_in_time and similar_haptic:
            return "suppress", "Suppress repeated speech because risks and actions have not changed recently"
        return "update", None

    def _reasoning_summary(
        self,
        priority: Severity,
        risks: list[str],
        actions: list[str],
        trigger: str,
    ) -> str:
        risk_text = "; ".join(risks[:3])
        action_text = ", ".join(actions[:2])
        if priority == "danger":
            return f"High risk takes priority: {risk_text}. Recommended action: {action_text}."
        if priority == "warn":
            return f"Moderate risk detected: {risk_text}. Recommended action: {action_text}."
        if trigger == "suppress":
            return "The context is stable. Keep prompts infrequent to reduce cognitive load."
        return f"Current risk is low: {risk_text}. Recommended action: {action_text}."

    def _region_text(self, label: str, direction: str) -> str:
        labels = {
            "vegetation": "vegetation",
            "tactile_paving": "tactile paving",
            "road_or_asphalt": "roadway",
            "walkable_pavement": "walkable pavement",
        }
        directions = {"left": "on the left", "center": "ahead", "right": "on the right", "unknown": "nearby"}
        return f"{labels.get(label, label)} {directions.get(direction, direction)}"
