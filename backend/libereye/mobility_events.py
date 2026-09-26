from __future__ import annotations

import math
from typing import Dict, List, Sequence

from .models import HapticPattern, MobilityEvent, Severity
from .wrist_haptics import WRIST_CUE_PRIORITY_RANK

# Module source identifiers (Section 2.1)
MODULE_OBSTACLE_TACTILE = "obstacles_tactile"
MODULE_TRAFFIC_CROSSINGS = "traffic_crossings"
MODULE_SEARCH_SCENE_TEXT = "search_scene_text"

# Engineering defaults. Section 2.2 specifies module gates, not numeric values.
MODULE_CONFIDENCE_GATES: Dict[str, float] = {
    MODULE_OBSTACLE_TACTILE: 0.55,
    MODULE_TRAFFIC_CROSSINGS: 0.65,
    MODULE_SEARCH_SCENE_TEXT: 0.50,
}


def distance_to_d_cue(distance_m: float | None) -> HapticPattern | None:
    """Map nominal obstacle proximity to Table 1 D-level cues.

    Table 1 Nominal Proximity Bands:
    - 3 to 5 m       -> D1 (Light, 0.15s, 0.5 Hz)
    - 1.5 to 3 m     -> D2 (Light, 0.15s, 1.0 Hz)
    - 0.8 to 1.5 m   -> D3 (Medium, 0.20s, 2.0 Hz)
    - Below 0.8 m    -> D4 (Medium, 0.20s, 4.0 Hz)
    """
    # Invalid depth must not manufacture a proximity cue. Boundary ties at
    # 1.5 m and 3 m escalate to the nearer band as an engineering convention.
    if distance_m is None or not math.isfinite(distance_m) or distance_m < 0:
        return None
    if distance_m < 0.8:
        return "D4"
    if distance_m <= 1.5:
        return "D3"
    if distance_m <= 3.0:
        return "D2"
    if distance_m <= 5.0:
        return "D1"
    return None


def event_passes_confidence_gate(
    event: MobilityEvent,
    confidence_gates: Dict[str, float] | None = None,
) -> bool:
    gates = MODULE_CONFIDENCE_GATES if confidence_gates is None else confidence_gates
    gate = gates.get(event.source_module, 0.50)
    return math.isfinite(event.confidence) and 0 <= event.confidence <= 1 and event.confidence >= gate


def extract_candidate_cues(
    events: Sequence[MobilityEvent],
    confidence_gates: Dict[str, float] | None = None,
) -> List[HapticPattern]:
    """Extract candidate wrist cues H_t from relevant events passing confidence gates.

    (Section 2.2: 'relevant events that pass module-specific confidence gates
    provide candidate wrist cues.')
    """
    candidate_cues: List[HapticPattern] = []
    for event in events:
        if event.is_optional_description or not event.candidate_wrist_cue:
            continue
        if not any(modality in {"bracelet", "wrist_haptic"} for modality in event.modalities):
            continue
        if event.candidate_wrist_cue not in WRIST_CUE_PRIORITY_RANK:
            raise ValueError(f"Unknown wrist cue: {event.candidate_wrist_cue}")
        if event_passes_confidence_gate(event, confidence_gates):
            candidate_cues.append(event.candidate_wrist_cue)
    return candidate_cues


def select_highest_priority_cue(candidate_cues: Sequence[HapticPattern]) -> HapticPattern | None:
    """Select highest-priority wrist cue under Equation (2):

    W3 > W2 > W1 > D4 > D3 > D2 > D1
    """
    if not candidate_cues:
        return None
    unknown = set(candidate_cues) - WRIST_CUE_PRIORITY_RANK.keys()
    if unknown:
        raise ValueError(f"Unknown wrist cues: {sorted(unknown)}")
    return max(candidate_cues, key=WRIST_CUE_PRIORITY_RANK.__getitem__)


def fuse_severities(events: Sequence[MobilityEvent]) -> Severity:
    """Compute fused severity s_t across active mobility events."""
    ranks = {"info": 0, "warn": 1, "danger": 2}
    max_rank = 0
    fused: Severity = "info"
    for e in events:
        r = ranks.get(e.severity, 0)
        if r > max_rank:
            max_rank = r
            fused = e.severity
    return fused
