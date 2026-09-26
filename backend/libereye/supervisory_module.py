from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from typing import List, Sequence

from .models import MobilityEvent, SceneState, Severity


@dataclass(frozen=True)
class SupervisoryDecision:
    """Decision output of the supervisory software module (Section 2.2).

    Attributes:
        override (o_t): Boolean flag triggering immediate override.
        fused_severity (s_t): Severity level across sensors and perception.
        override_wrist_cue: Table 1 W3 cue when override is active.
        stop_instruction: Action instruction retained in the assistance plan.
        voice_override: Spoken stop message.
        notes: Audit notes for safety and sensor health.
    """
    override: bool
    fused_severity: Severity
    override_wrist_cue: str | None = None
    stop_instruction: str | None = None
    voice_override: str | None = None
    notes: List[str] = field(default_factory=list)


class SupervisoryModule:
    """Supervisory software module (Section 2.2).

    'A supervisory software module can override the plan for traffic,
    sensor-health, or immediate-risk conditions. An override selects W3
    and a stop instruction.'
    """

    def __init__(self, max_frame_age_s: float = 1.5, min_confidence: float = 0.55) -> None:
        # Numeric thresholds are engineering defaults, not reported paper values.
        if not math.isfinite(max_frame_age_s) or max_frame_age_s <= 0:
            raise ValueError("max_frame_age_s must be finite and positive")
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between zero and one")
        self.max_frame_age_s = max_frame_age_s
        self.min_confidence = min_confidence

    def evaluate(self, scene: SceneState, events: Sequence[MobilityEvent] | None = None) -> SupervisoryDecision:
        notes: List[str] = []
        now = time.time()
        frame_age_s = now - scene.timestamp_s

        override = False
        fused_severity: Severity = "info"
        stop_instruction: str | None = None
        voice_override: str | None = None

        # 1. Sensor-health conditions
        if not math.isfinite(scene.timestamp_s) or frame_age_s < -0.5:
            notes.append("Invalid or future perception timestamp")
            fused_severity = "danger"
            override = True
            stop_instruction = "Safety protection: invalid perception time. Stop immediately and reconfirm the surroundings"
            voice_override = "Stop. Perception time is invalid. Stay in place."
        elif frame_age_s > self.max_frame_age_s:
            notes.append(f"Stale perception frame: {frame_age_s:.1f}s")
            fused_severity = "danger"
            override = True
            stop_instruction = "Safety protection: excessive perception delay. Stop immediately and reconfirm the surroundings"
            voice_override = "Stop. Perception delay is too high. Stay in place."

        if scene.sensor_health == "lost":
            notes.append("Critical sensor disconnected")
            fused_severity = "danger"
            override = True
            stop_instruction = "Safety protection: critical sensor disconnected. Stop immediately"
            voice_override = "Stop. Sensor disconnected. Stop and check."
        elif scene.sensor_health == "degraded":
            notes.append("Sensor status degraded")
            if fused_severity != "danger":
                fused_severity = "warn"

        # 2. Traffic override conditions (Section 2.2: 'For example, a traffic override selects W3')
        if scene.traffic_light == "red" and scene.traffic_confidence >= 0.65:
            notes.append("Red-light safety override")
            fused_severity = "danger"
            override = True
            stop_instruction = "Red light. Stop before the curb and wait"
            voice_override = "Red light. Wait before the curb."

        if scene.vehicle_approaching and scene.vehicle_confidence >= 0.65:
            notes.append("Approaching-vehicle safety override")
            fused_severity = "danger"
            override = True
            stop_instruction = "Approaching vehicle detected. Stop on the safe side and wait"
            voice_override = "Vehicle approaching. Stop immediately."

        # 3. Immediate-risk conditions (dominant road asphalt ahead without crossing)
        center_road = any(
            r.label == "road_or_asphalt" and r.direction == "center" and r.coverage >= 0.14 and r.confidence >= 0.65
            for r in scene.semantic_regions
        )
        if center_road and scene.user_intent != "cross":
            notes.append("Roadway-departure safety override")
            fused_severity = "danger"
            override = True
            stop_instruction = "Roadway hazard ahead. Stop immediately and reconfirm your direction"
            voice_override = "Roadway hazard. Stop immediately."

        # 4. Immediate collision range. This conservative engineering threshold
        # extends the paper's unspecified immediate-risk override condition.
        proximity = [(scene.obstacle_distance_m, scene.obstacle_confidence)]
        if scene.depth_estimate:
            proximity.append((scene.depth_estimate.center_depth_m, scene.depth_estimate.confidence))
        proximity.extend((obj.distance_m, obj.confidence) for obj in scene.detected_objects if obj.direction in {"center", "unknown"})
        if any(distance is not None and math.isfinite(distance) and 0 <= distance < 0.5 and self.min_confidence <= confidence <= 1 for distance, confidence in proximity):
            notes.append("Imminent-collision safety override")
            fused_severity = "danger"
            override = True
            stop_instruction = "Obstacle too close ahead. Stop immediately and check clearance with your white cane"
            voice_override = "Obstacle too close. Stop immediately."

        # 5. Integrate event severities
        if events:
            if any(e.severity == "danger" for e in events):
                fused_severity = "danger"
            elif any(e.severity == "warn" for e in events) and fused_severity != "danger":
                fused_severity = "warn"

        override_wrist_cue = "W3" if override else None

        return SupervisoryDecision(
            override=override,
            fused_severity=fused_severity,
            override_wrist_cue=override_wrist_cue,
            stop_instruction=stop_instruction,
            voice_override=voice_override,
            notes=notes,
        )
