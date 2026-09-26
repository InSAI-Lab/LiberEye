"""Synthetic software replay, separate from the paper's human study outcomes.

S, AH and AHC are release comparison policies, not the study's C0 to C3
conditions. Timing measures Python plan construction only. This module cannot
estimate near misses, NASA-TLX, SUS, physical haptic delivery or speech duration.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from statistics import median
from typing import Dict, List, Literal, Sequence

from .epmc import EPMCCoordinator
from .mobility_events import event_passes_confidence_gate, extract_candidate_cues
from .models import SceneState
from .scenarios import SCENARIOS

InterfaceCondition = Literal["S", "AH", "AHC"]


@dataclass
class ReplayMetrics:
    condition: InterfaceCondition
    total_frames: int = 0
    speech_suppressions: int = 0
    haptic_preemptions: int = 0
    median_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    override_count: int = 0
    total_cues_emitted: int = 0
    spoken_character_count: int = 0
    latency_scope: str = "synthetic_backend_plan_replay_only"
    physical_output_measured: bool = False


class CoordinationEvaluator:
    """Replay identical snapshots with three explicit output policies.

    S admits every eligible recommendation in module order, with no haptics.
    AH uses the same speech and queues every eligible distinct wrist cue.
    AHC applies Algorithm 1, including supervisor stop overrides.

    All policies use the same perception and supervisor. No output device is
    executed. A fresh coordinator per replay prevents FSM and metric carryover.
    """

    def __init__(self, coordinator: EPMCCoordinator | None = None) -> None:
        self.coordinator = coordinator or EPMCCoordinator()

    def run_replay(self, scenes: Sequence[SceneState], condition: InterfaceCondition = "AHC") -> ReplayMetrics:
        if condition not in {"S", "AH", "AHC"}:
            raise ValueError("condition must be S, AH or AHC; study conditions are not simulated")
        # Copy configured gates but discard prior replay state.
        coordinator = EPMCCoordinator(confidence_gates=self.coordinator.confidence_gates)
        latencies: List[float] = []
        metrics = ReplayMetrics(condition=condition, total_frames=len(scenes))
        for recorded_scene in scenes:
            # These fixture snapshots have no delivery clock. Set a fresh
            # observation time rather than turning import age into sensor loss.
            scene = replace(recorded_scene, timestamp_s=time.time())
            started = time.perf_counter()
            if condition == "AHC":
                plan = coordinator.analyze_scene(scene)
                metrics.speech_suppressions += int(plan.metadata["speech_suppression_occurred"])
                metrics.haptic_preemptions += int(plan.metadata["haptic_preemption_occurred"])
                metrics.override_count += int(plan.metadata["override"])
                metrics.total_cues_emitted += len(plan.haptics)
                metrics.spoken_character_count += len(plan.voice_message)
            else:
                events = coordinator.perception_pipeline.process(scene)
                decision = coordinator.supervisory_module.evaluate(scene, events)
                spoken = [event.recommendation for event in events if "voice" in event.modalities and event_passes_confidence_gate(event, coordinator.confidence_gates)]
                cues = list(dict.fromkeys(extract_candidate_cues(events, coordinator.confidence_gates)))
                if decision.override:
                    spoken.insert(0, decision.voice_override or decision.stop_instruction or "Stop")
                    if "W3" not in cues:
                        cues.insert(0, "W3")
                metrics.override_count += int(decision.override)
                metrics.total_cues_emitted += len(cues) if condition == "AH" else 0
                metrics.spoken_character_count += len(". ".join(spoken))
            latencies.append((time.perf_counter() - started) * 1000)
        if latencies:
            metrics.median_latency_ms = median(latencies)
            metrics.p95_latency_ms = sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
        return metrics

    def evaluate_benchmark_scenarios(self) -> Dict[InterfaceCondition, ReplayMetrics]:
        """Synthetic fixture replay; excludes all human performance estimates."""
        scenes = list(SCENARIOS.values())
        return {condition: self.run_replay(scenes, condition) for condition in ("S", "AH", "AHC")}
