from __future__ import annotations

import time
from dataclasses import dataclass

from .models import AgentResult, HapticCue, SceneState, Severity


SEVERITY_RANK = {"info": 0, "warn": 1, "danger": 2}


@dataclass(frozen=True)
class SafetyDecision:
    severity: Severity
    notes: list[str]
    override_instruction: str | None = None
    override_voice: str | None = None
    override_haptic: HapticCue | None = None


class SafetySupervisor:
    """Conservative guardrail for real-world mobility.

    This class intentionally biases toward slowing down or stopping when the
    perception stack is stale, missing, or uncertain.
    """

    def __init__(self, max_frame_age_s: float = 1.5, min_confidence: float = 0.45) -> None:
        self.max_frame_age_s = max_frame_age_s
        self.min_confidence = min_confidence

    def evaluate(self, scene: SceneState, results: list[AgentResult]) -> SafetyDecision:
        notes: list[str] = []
        severity: Severity = "info"
        now = time.time()
        frame_age_s = now - scene.timestamp_s

        if frame_age_s > self.max_frame_age_s:
            notes.append(f"Stale perception frame: {frame_age_s:.1f}s")
            severity = self._max_severity(severity, "danger")

        if scene.sensor_health == "lost":
            notes.append("Critical sensor disconnected")
            severity = self._max_severity(severity, "danger")
        elif scene.sensor_health == "degraded":
            notes.append("Sensor status degraded")
            severity = self._max_severity(severity, "warn")

        low_confidence_fields = self._low_confidence_fields(scene)
        if low_confidence_fields:
            notes.append("Low-confidence perception: " + ", ".join(low_confidence_fields))
            severity = self._max_severity(severity, "warn")

        if any(result.severity == "danger" for result in results):
            severity = self._max_severity(severity, "danger")
        elif any(result.severity == "warn" for result in results):
            severity = self._max_severity(severity, "warn")

        if severity == "danger" and notes:
            return SafetyDecision(
                severity="danger",
                notes=notes,
                override_instruction="Safety protection: stop immediately and wait for environmental confirmation",
                override_voice="Stop. Check the path ahead before continuing.",
                override_haptic=HapticCue("bracelet", "W3", 10, 100, "danger", "Safety protection: W3 emergency stop, one strong 1-second pulse and four rapid short pulses"),
            )

        if severity == "warn" and notes:
            return SafetyDecision(
                severity="warn",
                notes=notes,
                override_instruction=None,
                override_voice=None,
                override_haptic=None,
            )

        return SafetyDecision(severity=severity, notes=notes)

    def _low_confidence_fields(self, scene: SceneState) -> list[str]:
        fields: list[str] = []
        checks = [
            ("obstacle", scene.obstacle_distance_m is not None, scene.obstacle_confidence),
            ("tactile paving", scene.tactile_blocked, scene.tactile_confidence),
            ("traffic light", scene.traffic_light != "unknown", scene.traffic_confidence),
            ("vehicle", scene.user_intent == "cross", scene.vehicle_confidence),
            ("target object", scene.target_query is not None, scene.target_confidence),
        ]
        for label, active, confidence in checks:
            if active and confidence < self.min_confidence:
                fields.append(f"{label}({confidence:.2f})")
        return fields

    @staticmethod
    def _max_severity(current: Severity, candidate: Severity) -> Severity:
        return candidate if SEVERITY_RANK[candidate] > SEVERITY_RANK[current] else current


# Compatibility alias with Section 2.2 Supervisory Software Module
SupervisoryModule = SafetySupervisor
SupervisoryDecision = SafetyDecision
