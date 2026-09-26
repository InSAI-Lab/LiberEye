from __future__ import annotations

import time
import math
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Sequence

from .models import (
    AssistancePlan,
    AvoidancePlan,
    ContextPlan,
    HapticCue,
    MobilityEvent,
    PerceptionFrame,
    SceneState,
    Severity,
    SpatialAudioCue,
)
from .mobility_events import (
    MODULE_CONFIDENCE_GATES,
    extract_candidate_cues,
    event_passes_confidence_gate,
    fuse_severities,
    select_highest_priority_cue,
)
from .perception import SceneAdapter
from .perception_modules import BackendPerceptionPipeline
from .scene_persistence import ScenePersistenceFSM
from .supervisory_module import SupervisoryModule
from .wrist_haptics import create_haptic_cue


@dataclass(frozen=True)
class EPMCResult:
    """Result of Algorithm 1: EPMC for wrist-cue selection and speech admission."""
    wrist_cue: str | None  # ht
    description_gate: bool  # gt
    description_blocked: bool  # ut
    action_instruction: str  # concise action instruction (always eligible)
    eligible_scene_description: str | None  # optional scene detail (admitted if gt)
    fused_severity: Severity  # st
    override: bool  # ot
    context_change: bool  # Delta_t
    detail_request: bool  # qt
    candidate_cues: List[str] = field(default_factory=list)  # Ht
    suppression_occurred: bool = False
    preemption_occurred: bool = False


class EPMCCoordinator:
    """Event Priority Multimodal Coordination (EPMC) algorithm (Section 2.2, Alg. 1).

    Coordinates wrist-cue selection and scene-description admission using a
    shared event priority ordering while preserving concise action guidance.
    """

    def __init__(
        self,
        perception_pipeline: BackendPerceptionPipeline | None = None,
        supervisory_module: SupervisoryModule | None = None,
        persistence_fsm: ScenePersistenceFSM | None = None,
        confidence_gates: Dict[str, float] | None = None,
    ) -> None:
        self.perception_pipeline = perception_pipeline or BackendPerceptionPipeline()
        self.supervisory_module = supervisory_module or SupervisoryModule()
        self.fsm = persistence_fsm or ScenePersistenceFSM()
        self.scene_adapter = SceneAdapter()
        self.confidence_gates = dict(MODULE_CONFIDENCE_GATES if confidence_gates is None else confidence_gates)

        # Evaluation metrics (Table 2 & Section 3.2, 4)
        self.speech_suppression_count: int = 0
        self.haptic_preemption_count: int = 0
        self.total_updates: int = 0
        self.processing_latency_ms_samples: deque[float] = deque(maxlen=1024)
        # Deprecated name retained for callers. These are software timings only.
        self.alert_latency_ms_samples = self.processing_latency_ms_samples

    def coordinate(
        self,
        candidate_cues: Sequence[str],
        override: bool = False,
        fused_severity: Severity = "info",
        context_change: bool = False,
        detail_request: bool = False,
        events: Sequence[MobilityEvent] | None = None,
        override_instruction: str | None = None,
        override_voice: str | None = None,
    ) -> EPMCResult:
        """Executes Algorithm 1: EPMC for wrist-cue selection and speech admission.

        Require: Candidate cues Ht != empty; override ot
        Require: Severity st; context change Delta_t; detail request qt
        Ensure: Wrist cue ht and description gate gt
        """
        events = events or []
        # The paper leaves equal-cue ties unspecified. Use severity, confidence,
        # then stable input order, and never use optional detail as the action.
        action_events = [
            event for event in events
            if not event.is_optional_description and event.recommendation
            and "voice" in event.modalities
            and event_passes_confidence_gate(event, self.confidence_gates)
        ]
        severity_rank = {"info": 0, "warn": 1, "danger": 2}
        action_events.sort(key=lambda event: (severity_rank[event.severity], event.confidence), reverse=True)
        preemption_occurred = False
        suppression_occurred = False

        # 1: if ot then
        # 2:     ht <- W3
        # 3:     Retain the stop instruction in the plan
        # 4: else
        # 5:     ht <- highest-priority cue in Ht under (2)
        # 6: end if
        if override:
            h_t = "W3"
            action_instruction = override_instruction or "Stop immediately and check your surroundings"
        elif candidate_cues:
            h_t = select_highest_priority_cue(list(candidate_cues))
            # Match action instruction to selected cue or top event
            matching_event = next((e for e in action_events if e.candidate_wrist_cue == h_t), None)
            if matching_event and matching_event.recommendation:
                action_instruction = matching_event.recommendation
            else:
                action_instruction = self._default_instruction_for_cue(h_t)
        else:
            h_t = None
            # Empty H_t is a release extension to Algorithm 1. Voice-only
            # transit and crossing actions remain eligible without vibration.
            action_instruction = action_events[0].recommendation if action_events else "Check the path ahead with your white cane and proceed carefully"

        # Count competing plan candidates, including those displaced by an
        # override. This does not measure interruption of a physical vibration.
        if h_t and any(cue != h_t for cue in candidate_cues):
            preemption_occurred = True
            self.haptic_preemption_count += 1

        # 7: ut <- (ht in {W1, W2, W3, D4}) \lor (st = danger)
        u_t = (h_t in {"W1", "W2", "W3", "D4"}) or (fused_severity == "danger")

        # 8: gt <- \neg ut \land (Delta_t \lor qt)
        g_t = (not u_t) and (context_change or detail_request)

        # 9: Admit optional scene descriptions if gt
        # 10: Keep concise action instructions eligible
        optional_descs = [e.recommendation.rstrip(".") for e in events if e.is_optional_description and e.recommendation and "voice" in e.modalities and event_passes_confidence_gate(e, self.confidence_gates)]
        if g_t and optional_descs:
            admitted_desc = ". ".join(optional_descs) + "."
        else:
            admitted_desc = None
            if optional_descs and not g_t:
                suppression_occurred = True
                self.speech_suppression_count += 1

        return EPMCResult(
            wrist_cue=h_t,
            description_gate=g_t,
            description_blocked=u_t,
            action_instruction=action_instruction,
            eligible_scene_description=admitted_desc,
            fused_severity=fused_severity,
            override=override,
            context_change=context_change,
            detail_request=detail_request,
            candidate_cues=list(candidate_cues),
            suppression_occurred=suppression_occurred,
            preemption_occurred=preemption_occurred,
        )

    def analyze_perception(self, frame: PerceptionFrame, detail_request: bool = False) -> AssistancePlan:
        """Process incoming PerceptionFrame through the EPMC coordination pipeline."""
        return self.analyze_scene(self.scene_adapter.from_perception(frame), detail_request=detail_request)

    def analyze_scene(self, scene: SceneState, detail_request: bool = False) -> AssistancePlan:
        """Process SceneState through EPMC to generate an assistance plan (Section 2)."""
        t_start = time.perf_counter()
        self.total_updates += 1

        # 1. Update scene persistence FSM (Section 2.2)
        fsm_phase, context_change = self.fsm.update(scene.scene_type)
        # Release convention: the first observation establishes new context.
        # The paper does not specify initialization of Delta_t.
        context_change = context_change or self.total_updates == 1

        # 2. Check detail request qt (Section 2.2)
        # q_t is true if user explicitly requested finding, query, or chat
        q_t = detail_request or (scene.user_intent in {"find", "chat"}) or bool(scene.target_query)

        # 3. Backend perception modules emit mobility events (Section 2.1)
        events = self.perception_pipeline.process(scene)

        # 4. Supervisory software module evaluates overrides (Section 2.2)
        supervisory_dec = self.supervisory_module.evaluate(scene, events)

        # 5. Extract candidate cues Ht passing confidence gates
        candidate_cues = extract_candidate_cues(events, self.confidence_gates)

        # Fuse severities
        event_severity = fuse_severities(events)
        fused_severity = max((supervisory_dec.fused_severity, event_severity), key={"info": 0, "warn": 1, "danger": 2}.__getitem__)

        # 6. Execute Algorithm 1 (EPMC)
        epmc_res = self.coordinate(
            candidate_cues=candidate_cues,
            override=supervisory_dec.override,
            fused_severity=fused_severity,
            context_change=context_change,
            detail_request=q_t,
            events=events,
            override_instruction=supervisory_dec.stop_instruction,
            override_voice=supervisory_dec.voice_override,
        )

        # 7. Construct assistance plan
        haptics: List[HapticCue] = []
        if epmc_res.wrist_cue:
            haptics.append(create_haptic_cue(epmc_res.wrist_cue))

        # Concise action guidance remains eligible for speech.
        # If description gate gt is True, eligible scene descriptions are appended.
        action_speech = (supervisory_dec.voice_override or epmc_res.action_instruction).rstrip(".")
        if epmc_res.description_gate and epmc_res.eligible_scene_description:
            voice_message = f"{action_speech}. {epmc_res.eligible_scene_description}"
        else:
            voice_message = f"{action_speech}."

        # Spatial audio and avoidance plan
        spatial_audio = self._plan_spatial_audio(scene, epmc_res)
        avoidance_plan = self._plan_avoidance(scene, epmc_res)

        # Context plan for backwards compatibility
        context_plan = ContextPlan(
            static_context=[scene.description],
            dynamic_risks=supervisory_dec.notes or ["No clear dynamic hazard detected"],
            action_steps=[epmc_res.action_instruction],
            reasoning_summary=f"EPMC decision: haptic={epmc_res.wrist_cue}, description_gate={epmc_res.description_gate}",
            reminder_trigger="urgent" if supervisory_dec.override or epmc_res.description_blocked else "update",
            should_speak=True,
            redundancy_reason=("Description suppressed by a higher-priority warning" if epmc_res.description_blocked else "Scene unchanged and no detail requested") if not epmc_res.description_gate else None,
        )

        processing_latency_ms = (time.perf_counter() - t_start) * 1000.0
        self.processing_latency_ms_samples.append(processing_latency_ms)
        median_latency = median(self.processing_latency_ms_samples)

        metadata: Dict[str, Any] = {
            "fsm_phase": fsm_phase,
            "wrist_cue": epmc_res.wrist_cue,
            "description_gate": epmc_res.description_gate,
            "description_blocked": epmc_res.description_blocked,
            "speech_suppression_count": self.speech_suppression_count,
            "haptic_preemption_count": self.haptic_preemption_count,
            "median_alert_latency_ms": round(median_latency, 2),
            "processing_latency_ms": processing_latency_ms,
            "median_processing_latency_ms": median_latency,
            "latency_scope": "backend_scene_coordination_only",
            "physical_output_measured": False,
            "coordinator": "epmc",
            "speech_suppression_occurred": epmc_res.suppression_occurred,
            "haptic_preemption_occurred": epmc_res.preemption_occurred,
            "candidate_cues": epmc_res.candidate_cues,
            "override": supervisory_dec.override,
            "context_change": context_change,
            "detail_request": q_t,
        }

        return AssistancePlan(
            scenario=scene.name,
            main_instruction=epmc_res.action_instruction,
            secondary_instruction=f"EPMC wrist command: {epmc_res.wrist_cue or 'none'}",
            priority=epmc_res.fused_severity,
            voice_message=voice_message,
            haptics=haptics,
            spatial_audio=spatial_audio,
            avoidance_plan=avoidance_plan,
            transit_cue=scene.transit_cue,
            agent_results=[],
            safety_notes=supervisory_dec.notes,
            context_plan=context_plan,
            cognitive_load={},
            study_metrics={},
            metadata=metadata,
            wrist_cue=epmc_res.wrist_cue,
            description_gate=epmc_res.description_gate,
            description_blocked=epmc_res.description_blocked,
            action_instruction=epmc_res.action_instruction,
            eligible_scene_description=epmc_res.eligible_scene_description,
            mobility_events=events,
        )

    def _default_instruction_for_cue(self, cue: str) -> str:
        instructions = {
            "W3": "Emergency stop. Do not move",
            "W2": "Avoidance needed. Stop first and confirm a traversable direction",
            "W1": "Hazard warning. Slow down and observe",
            "D4": "Very close obstacle. Stop immediately or slow down",
            "D3": "Close obstacle. Continue slowly",
            "D2": "Medium-distance obstacle. Be ready to avoid it",
            "D1": "Distant obstacle. Keep observing",
        }
        return instructions.get(cue, "Continue straight")

    def _plan_spatial_audio(self, scene: SceneState, epmc_res: EPMCResult) -> List[SpatialAudioCue]:
        cues: List[SpatialAudioCue] = []
        nearest = min(
            (obj for obj in scene.detected_objects if obj.distance_m is not None
             and math.isfinite(obj.distance_m) and obj.distance_m >= 0
             and self.confidence_gates.get("obstacles_tactile", 0.55) <= obj.confidence <= 1),
            key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
            default=None,
        )
        if nearest and nearest.distance_m is not None and nearest.distance_m <= 3.2:
            azimuth = {"left": -45, "center": 0, "right": 45, "unknown": 0}.get(nearest.direction, 0)
            sev = "danger" if nearest.distance_m <= 1.5 else "warn"
            cues.append(
                SpatialAudioCue(
                    direction=nearest.direction,
                    azimuth_deg=azimuth,
                    message=f"{nearest.label} to the {nearest.direction}, about {nearest.distance_m:.1f} m away",
                    priority=sev,
                    volume=1.0 if sev == "danger" else 0.8,
                )
            )
        return cues

    def _plan_avoidance(self, scene: SceneState, epmc_res: EPMCResult) -> AvoidancePlan:
        if epmc_res.wrist_cue == "W3" or epmc_res.fused_severity == "danger":
            return AvoidancePlan("stop", 0, "Safety stop for high risk", 0.95)
        if epmc_res.wrist_cue == "W2":
            depth = scene.depth_estimate
            if depth and depth.confidence >= self.confidence_gates.get("obstacles_tactile", 0.55) and depth.left_clearance_m is not None and math.isfinite(depth.left_clearance_m) and depth.left_clearance_m > 1:
                return AvoidancePlan("veer_left", -20, "Use the estimated space on the left to detour cautiously, checking with your white cane", depth.confidence)
            return AvoidancePlan("slow_down", 0, "Avoidance direction is unconfirmed. Slow down and probe with your white cane", 0.0)
        if epmc_res.wrist_cue in {"D4", "D3"}:
            return AvoidancePlan("slow_down", 0, "Slow down for a nearby obstacle", 0.85)
        return AvoidancePlan("proceed", 0, "No stop or avoidance triggered. Continue checking the surroundings with your white cane", 0.0)

    def _study_metrics(self, scene: SceneState) -> Dict[str, str]:
        """Human study outcomes cannot be estimated from a scene update."""
        return {}
