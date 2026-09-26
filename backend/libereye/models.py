from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Literal


Severity = Literal["info", "warn", "danger"]
HapticPattern = Literal["D1", "D2", "D3", "D4", "W1", "W2", "W3"]
Modality = Literal["voice", "bracelet", "phone"]
AgentPriority = Literal["CRITICAL", "GUIDANCE", "CONTEXT", "ON_DEMAND"]
Direction = Literal["left", "center", "right", "unknown"]


@dataclass(frozen=True)
class DetectedObject:
    label: str
    direction: Direction
    distance_m: float | None = None
    confidence: float = 1.0
    bbox: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticRegion:
    label: str
    direction: Direction
    coverage: float
    confidence: float = 1.0


@dataclass(frozen=True)
class DepthEstimate:
    min_depth_m: float | None = None
    center_depth_m: float | None = None
    left_clearance_m: float | None = None
    right_clearance_m: float | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class SpatialAudioCue:
    direction: Direction
    azimuth_deg: int
    message: str
    priority: Severity
    volume: float = 0.8


@dataclass(frozen=True)
class AvoidancePlan:
    action: Literal["stop", "slow_down", "veer_left", "veer_right", "proceed"]
    heading_delta_deg: int
    rationale: str
    confidence: float = 1.0


@dataclass(frozen=True)
class TransitCue:
    stop_name: str | None = None
    route_name: str | None = None
    distance_m: float | None = None
    direction: Direction = "unknown"
    next_action: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class SceneState:
    name: str
    description: str
    obstacle_distance_m: float | None = None
    obstacle_confidence: float = 1.0
    tactile_blocked: bool = False
    tactile_confidence: float = 1.0
    traffic_light: Literal["red", "yellow", "green", "unknown"] = "unknown"
    traffic_confidence: float = 1.0
    vehicle_approaching: bool = False
    vehicle_confidence: float = 1.0
    target_query: str | None = None
    target_distance_m: float | None = None
    target_direction: Literal["left", "center", "right", "unknown"] = "unknown"
    target_confidence: float = 0.0
    crowd_level: Literal["low", "medium", "high"] = "low"
    user_intent: Literal["navigate", "cross", "find", "chat", "transit"] = "navigate"
    scene_type: Literal["sidewalk", "street", "blocked", "crossing", "finding", "transit", "indoor", "unknown"] = "unknown"
    scene_label: str | None = None
    detected_objects: List[DetectedObject] = field(default_factory=list)
    semantic_regions: List[SemanticRegion] = field(default_factory=list)
    depth_estimate: DepthEstimate | None = None
    transit_cue: TransitCue | None = None
    detected_texts: List[str] = field(default_factory=list)
    sign_candidates: List[str] = field(default_factory=list)
    scene_description: str | None = None
    sensor_health: Literal["ok", "degraded", "lost"] = "ok"
    timestamp_s: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "detected_objects", [_object_from_value(obj) for obj in self.detected_objects])
        object.__setattr__(self, "semantic_regions", [_region_from_value(region) for region in self.semantic_regions])
        if self.depth_estimate is not None and isinstance(self.depth_estimate, dict):
            object.__setattr__(self, "depth_estimate", DepthEstimate(**self.depth_estimate))
        if self.transit_cue is not None and isinstance(self.transit_cue, dict):
            object.__setattr__(self, "transit_cue", TransitCue(**self.transit_cue))


@dataclass(frozen=True)
class AgentResult:
    agent_id: str
    agent_name: str
    status: str
    severity: Severity
    confidence: float
    recommendation: str
    modalities: List[Modality] = field(default_factory=list)
    focus: str = ""
    priority: AgentPriority = "ON_DEMAND"


# Haptic codes shared by backend, iOS app, Arduino firmware, and paper:
# D1-D4 encode distance proximity; W1-W3 encode urgent warnings.
@dataclass(frozen=True)
class HapticCue:
    device: Literal["bracelet"]
    pattern: HapticPattern
    frequency_hz: float
    intensity: int
    risk_level: Severity
    meaning: str


@dataclass(frozen=True)
class ContextPlan:
    static_context: List[str]
    dynamic_risks: List[str]
    action_steps: List[str]
    reasoning_summary: str
    reminder_trigger: Literal["urgent", "update", "suppress"]
    should_speak: bool
    redundancy_reason: str | None = None


@dataclass(frozen=True)
class MobilityEvent:
    """Structured mobility event e_i = <a_i, s_i, c_i, M_i, r_i> (Section 2.1, Eq. 1).

    Attributes:
        source_module (a_i): Identifier of the source perception module.
        severity (s_i): Severity level ('info', 'warn', 'danger').
        confidence (c_i): Module-provided confidence score in [0.0, 1.0].
        modalities (M_i): Candidate output modalities ('voice', 'bracelet', 'phone').
        recommendation (r_i): Concise recommendation or action guidance.
        candidate_wrist_cue: Output wrist cue (D1-D4, W1-W3) if bracelet is eligible.
        is_optional_description: True if this event is optional scene detail subject to gate g_t.
        timestamp_s: Timestamp of event generation.
        metadata: Module-specific auxiliary evidence.
    """
    source_module: str
    severity: Severity
    confidence: float
    modalities: List[Modality] = field(default_factory=lambda: ["voice", "bracelet"])
    recommendation: str = ""
    candidate_wrist_cue: HapticPattern | None = None
    is_optional_description: bool = False
    timestamp_s: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssistancePlan:
    scenario: str
    main_instruction: str
    secondary_instruction: str
    priority: Severity
    voice_message: str
    haptics: List[HapticCue]
    spatial_audio: List[SpatialAudioCue]
    avoidance_plan: AvoidancePlan
    transit_cue: TransitCue | None
    agent_results: List[AgentResult]
    safety_notes: List[str]
    context_plan: ContextPlan
    cognitive_load: Dict[str, int]
    study_metrics: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    wrist_cue: str | None = None
    description_gate: bool = True
    description_blocked: bool = False
    action_instruction: str = ""
    eligible_scene_description: str | None = None
    mobility_events: List[MobilityEvent] = field(default_factory=list)


@dataclass(frozen=True)
class PerceptionFrame:
    """Normalized perception output from camera, glasses, GPS, or model services."""

    obstacle_distance_m: float | None = None
    obstacle_confidence: float = 1.0
    tactile_blocked: bool = False
    tactile_confidence: float = 1.0
    traffic_light: Literal["red", "yellow", "green", "unknown"] = "unknown"
    traffic_confidence: float = 1.0
    vehicle_approaching: bool = False
    vehicle_confidence: float = 1.0
    target_query: str | None = None
    target_distance_m: float | None = None
    target_direction: Literal["left", "center", "right", "unknown"] = "unknown"
    target_confidence: float = 0.0
    crowd_level: Literal["low", "medium", "high"] = "low"
    user_intent: Literal["navigate", "cross", "find", "chat", "transit"] = "navigate"
    scene_type: Literal["sidewalk", "street", "blocked", "crossing", "finding", "transit", "indoor", "unknown"] = "unknown"
    scene_label: str | None = None
    detected_objects: List[DetectedObject] = field(default_factory=list)
    semantic_regions: List[SemanticRegion] = field(default_factory=list)
    depth_estimate: DepthEstimate | None = None
    transit_cue: TransitCue | None = None
    detected_texts: List[str] = field(default_factory=list)
    sign_candidates: List[str] = field(default_factory=list)
    scene_description: str | None = None
    sensor_health: Literal["ok", "degraded", "lost"] = "ok"
    timestamp_s: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(self, "detected_objects", [_object_from_value(obj) for obj in self.detected_objects])
        object.__setattr__(self, "semantic_regions", [_region_from_value(region) for region in self.semantic_regions])
        if self.depth_estimate is not None and isinstance(self.depth_estimate, dict):
            object.__setattr__(self, "depth_estimate", DepthEstimate(**self.depth_estimate))
        if self.transit_cue is not None and isinstance(self.transit_cue, dict):
            object.__setattr__(self, "transit_cue", TransitCue(**self.transit_cue))


def _object_from_value(value: DetectedObject | dict) -> DetectedObject:
    if isinstance(value, DetectedObject):
        return value
    return DetectedObject(**value)


def _region_from_value(value: SemanticRegion | dict) -> SemanticRegion:
    if isinstance(value, SemanticRegion):
        return value
    return SemanticRegion(**value)
