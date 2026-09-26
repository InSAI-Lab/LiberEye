from __future__ import annotations

import time
from collections import deque
from dataclasses import replace

from .specialists import DEFAULT_AGENTS, Agent, FindingAgent
from .context_planner import MobilityContextPlanner
from .models import AgentPriority, AgentResult, AssistancePlan, AvoidancePlan, HapticCue, PerceptionFrame, SceneState, SpatialAudioCue
from .perception import SceneAdapter
from .safety import SafetySupervisor
from .scenarios import SCENARIOS
from .epmc import EPMCCoordinator, EPMCResult


SEVERITY_RANK = {"info": 0, "warn": 1, "danger": 2}
SEVERITY_INT = {"info": 0, "warn": 1, "danger": 2}
DIRECTION_LABELS = {"left": "on the left", "center": "ahead", "right": "on the right", "unknown": "nearby"}
REGION_LABELS = {
    "vegetation": "vegetation",
    "tactile_paving": "tactile paving",
    "crosswalk": "crosswalk",
    "road_or_asphalt": "roadway/asphalt",
    "walkable_pavement": "walkable pavement",
}
OBJECT_LABELS = {
    "person": "pedestrian",
    "bicycle": "bicycle",
    "car": "car",
    "motorcycle": "motorcycle",
    "bus": "bus",
    "truck": "truck",
    "traffic light": "traffic light",
    "traffic_light": "traffic light",
    "traffic_light_red": "Red light",
    "traffic_light_green": "Green light",
    "traffic_light_yellow": "Yellow light",
    "obstacle": "obstacle",
    "person_or_obstacle": "pedestrian/obstacle",
    "segmented_object": "segmented object",
}

# Scene-to-agent mapping for Dynamic Agent Gating
# Agents not in the active set for the current scene are skipped.
SCENE_AGENT_MAP: dict[str, set[str]] = {
    "sidewalk": {"obstacle", "tactile", "object", "depth", "semantic", "route", "avoidance", "spatial_audio", "scene", "text", "sign", "intent"},
    "street": {"obstacle", "tactile", "object", "depth", "semantic", "route", "avoidance", "spatial_audio", "scene", "text", "sign", "intent"},
    "crossing": {"obstacle", "object", "depth", "traffic", "crossing", "spatial_audio", "avoidance", "scene", "intent"},
    "blocked": {"obstacle", "tactile", "object", "depth", "semantic", "route", "avoidance", "scene", "intent"},
    "finding": {"obstacle", "object", "depth", "finding", "spatial_audio", "text", "sign", "scene", "intent"},
    "transit": {"obstacle", "object", "depth", "transit", "spatial_audio", "text", "sign", "scene", "intent"},
    "indoor": {"object", "scene", "text", "sign", "intent"},
    "unknown": {agent.agent_id for agent in DEFAULT_AGENTS},  # all agents for unknown scenes
}

# FSM state transition graph
FSM_TRANSITIONS: dict[str, dict[str, str]] = {
    "sidewalk": {"sidewalk": "sidewalk", "street": "sidewalk", "crossing": "approaching_crossing", "blocked": "sidewalk", "finding": "sidewalk", "transit": "sidewalk", "indoor": "sidewalk", "unknown": "sidewalk"},
    "approaching_crossing": {"sidewalk": "sidewalk", "street": "sidewalk", "crossing": "crossing", "blocked": "sidewalk", "finding": "sidewalk", "transit": "sidewalk", "indoor": "sidewalk", "unknown": "approaching_crossing"},
    "crossing": {"sidewalk": "recovery", "street": "recovery", "crossing": "crossing", "blocked": "recovery", "finding": "recovery", "transit": "recovery", "indoor": "recovery", "unknown": "crossing"},
    "recovery": {"sidewalk": "sidewalk", "street": "sidewalk", "crossing": "approaching_crossing", "blocked": "sidewalk", "finding": "sidewalk", "transit": "sidewalk", "indoor": "sidewalk", "unknown": "recovery"},
}


class SceneFSM:
    """Scene Finite State Machine with hysteresis.

    Maintains sidewalk→approaching_crossing→crossing→recovery state transitions.
    Requires N=3 consecutive frames agreeing on a scene type before transitioning,
    preventing single-frame jitter from triggering state changes.
    """

    HYSTERESIS_N = 3

    def __init__(self) -> None:
        self.state: str = "sidewalk"
        self._candidate: str = "sidewalk"
        self._candidate_count: int = 0

    def update(self, scene_type: str) -> str:
        """Update FSM with new scene_type observation. Returns current FSM state."""
        # Normalize scene_type to FSM-known types
        normalized = scene_type if scene_type in FSM_TRANSITIONS.get(self.state, {}) else "unknown"

        if normalized == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = normalized
            self._candidate_count = 1

        # Only transition when hysteresis threshold is met
        if self._candidate_count >= self.HYSTERESIS_N:
            next_state = FSM_TRANSITIONS.get(self.state, {}).get(normalized, self.state)
            self.state = next_state

        return self.state


class MobilityOrchestrator:
    def __init__(
        self,
        agents: list[Agent] | None = None,
        safety: SafetySupervisor | None = None,
        context_planner: MobilityContextPlanner | None = None,
        bracelet_driver=None,
    ) -> None:
        self.agents = agents or DEFAULT_AGENTS
        self.safety = safety or SafetySupervisor()
        self.scene_adapter = SceneAdapter()
        self.context_planner = context_planner or MobilityContextPlanner()
        self.bracelet_driver = bracelet_driver
        self.fsm = SceneFSM()
        # Metrics
        self.event_conflict_rate: float = 0.0
        self.speech_suppression_count: int = 0
        self.alert_latency_ms_samples: list[float] = []
        self._total_frames: int = 0
        self._conflict_frames: int = 0

    @property
    def crossing_mode(self) -> str:
        return self.fsm.state

    def available_scenarios(self) -> list[dict[str, str]]:
        return [{"id": key, "description": scene.description} for key, scene in SCENARIOS.items()]

    def analyze_scenario(self, scenario_id: str) -> AssistancePlan:
        if scenario_id not in SCENARIOS:
            valid = ", ".join(SCENARIOS)
            raise ValueError(f"Unknown scenario '{scenario_id}'. Valid scenarios: {valid}")
        return self.analyze_scene(replace(SCENARIOS[scenario_id], timestamp_s=time.time()))

    def analyze_perception(self, frame: PerceptionFrame) -> AssistancePlan:
        return self.analyze_scene(self.scene_adapter.from_perception(frame))

    def analyze_scene(self, scene: SceneState) -> AssistancePlan:
        t_start = time.time()
        self._total_frames += 1

        # Update Scene FSM with hysteresis
        self.fsm.update(scene.scene_type)

        # Dynamic Agent Gating: only run agents relevant to current scene
        active_agents = self._gate_agents(scene)
        active_count = len(active_agents)

        results = [self._with_agent_focus(agent.analyze(scene), scene) for agent in active_agents]

        # Assign priority to each result based on FSM state and severity
        results = [self._assign_priority(r, scene) for r in results]

        # Confidence-Weighted Fusion replaces max(severity)
        priority_result = self._fuse_results(results)

        # Track conflict rate: conflict = top-2 results have different severity
        if len(results) >= 2:
            sorted_results = sorted(results, key=lambda r: SEVERITY_RANK[r.severity], reverse=True)
            if sorted_results[0].severity != sorted_results[1].severity:
                self._conflict_frames += 1
        self.event_conflict_rate = self._conflict_frames / self._total_frames

        avoidance_plan = self._plan_avoidance(scene)
        spatial_audio = self._plan_spatial_audio(scene, priority_result)
        haptics = self._plan_haptics(scene, results)
        main, secondary = self._compose_instructions(scene, priority_result)
        voice_message = self._compose_voice(scene, priority_result)
        safety_decision = self.safety.evaluate(scene, results)

        if safety_decision.override_haptic:
            haptics = [safety_decision.override_haptic]
        if safety_decision.override_instruction:
            main = safety_decision.override_instruction
            secondary = "Conservative mode: stop moving and reconfirm sensors and surroundings."
        if safety_decision.override_voice:
            voice_message = safety_decision.override_voice

        context_plan = self.context_planner.plan(
            scene=scene,
            results=results,
            priority=safety_decision.severity,
            main_instruction=main,
            haptics=haptics,
            safety_notes=safety_decision.notes,
        )

        # Track suppression count
        if not context_plan.should_speak:
            self.speech_suppression_count += 1

        # Track alert latency
        t_end = time.time()
        self.alert_latency_ms_samples.append((t_end - t_start) * 1000.0)

        # Cognitive load-aware modality dispatch
        cognitive_load = self._compute_cognitive_load(results, scene, active_count)

        # Build metadata dict
        latency_samples = self.alert_latency_ms_samples
        median_latency = sorted(latency_samples)[len(latency_samples) // 2] if latency_samples else 0.0
        metadata: dict = {
            "event_conflict_rate": round(self.event_conflict_rate, 4),
            "speech_suppression_count": self.speech_suppression_count,
            "median_alert_latency_ms": round(median_latency, 2),
            "active_agent_count": active_count,
            "total_agent_count": len(self.agents),
            "fsm_state": self.fsm.state,
        }

        top_cue = haptics[0].pattern if haptics else None
        u_t = (top_cue in {"W1", "W2", "W3", "D4"}) or (safety_decision.severity == "danger")
        g_t = not u_t

        return AssistancePlan(
            scenario=scene.name,
            main_instruction=main,
            secondary_instruction=secondary,
            priority=safety_decision.severity,
            voice_message=voice_message,
            haptics=haptics,
            spatial_audio=spatial_audio,
            avoidance_plan=avoidance_plan,
            transit_cue=scene.transit_cue,
            agent_results=results,
            safety_notes=safety_decision.notes,
            context_plan=context_plan,
            cognitive_load=cognitive_load,
            study_metrics={},
            metadata=metadata,
            wrist_cue=top_cue,
            description_gate=g_t,
            description_blocked=u_t,
            action_instruction=main,
            eligible_scene_description=scene.scene_description if g_t else None,
        )

    def _gate_agents(self, scene: SceneState) -> list[Agent]:
        """Return only agents active for the current scene type."""
        active_ids = SCENE_AGENT_MAP.get(scene.scene_type, SCENE_AGENT_MAP["unknown"])
        return [agent for agent in self.agents if agent.agent_id in active_ids]

    def _assign_priority(self, result: AgentResult, scene: SceneState) -> AgentResult:
        """Assign AgentPriority based on FSM state and severity."""
        fsm_state = self.fsm.state
        if result.severity == "danger":
            priority: AgentPriority = "CRITICAL"
        elif result.severity == "warn" and fsm_state in {"crossing", "approaching_crossing"}:
            priority = "CRITICAL"
        elif result.severity == "warn":
            priority = "GUIDANCE"
        elif fsm_state in {"crossing", "approaching_crossing"}:
            priority = "GUIDANCE"
        else:
            priority = "CONTEXT" if result.severity == "info" else "ON_DEMAND"
        return replace(result, priority=priority)

    def _fuse_results(self, results: list[AgentResult]) -> AgentResult:
        """Confidence-Weighted Fusion: Σ(conf_i × sev_i) / Σconf_i."""
        if not results:
            from .specialists import SceneDescriptionAgent
            return AgentResult("scene", "Scene description specialist", "No result", "info", 0.5, "Continue forward")
        total_weight = sum(r.confidence for r in results)
        if total_weight == 0:
            return max(results, key=lambda r: SEVERITY_RANK[r.severity])
        weighted_sum = sum(r.confidence * SEVERITY_INT[r.severity] for r in results)
        fused_score = weighted_sum / total_weight
        # Round to nearest discrete level
        if fused_score >= 1.5:
            target_severity = "danger"
        elif fused_score >= 0.5:
            target_severity = "warn"
        else:
            target_severity = "info"
        # Return the highest-confidence result matching the fused severity level
        matching = [r for r in results if r.severity == target_severity]
        if matching:
            return max(matching, key=lambda r: r.confidence)
        return max(results, key=lambda r: SEVERITY_RANK[r.severity])

    def _compute_cognitive_load(self, results: list[AgentResult], scene: SceneState, active_count: int) -> dict[str, int]:
        """Cognitive Load-Aware Modality Dispatch with L-score three-tier output."""
        danger_count = sum(r.severity == "danger" for r in results)
        warn_count = sum(r.severity == "warn" for r in results)
        # Normalize components to [0, 1]
        agent_load = min(active_count / max(len(self.agents), 1), 1.0)
        danger_weight = min(danger_count * 0.3 + warn_count * 0.1, 1.0)
        scene_complexity = 0.7 if scene.scene_type in {"crossing", "blocked"} else 0.3
        L = (agent_load * 0.3 + danger_weight * 0.5 + scene_complexity * 0.2)
        if L < 0.3:
            # Voice-first
            return {"voice": 70, "haptic": 30}
        elif L <= 0.7:
            # Balanced
            return {"voice": 50, "haptic": 50}
        else:
            # Haptic-first
            return {"voice": 30, "haptic": 70}

    def _compose_instructions(self, scene: SceneState, priority: AgentResult) -> tuple[str, str]:
        if scene.traffic_light == "red" or scene.vehicle_approaching:
            return "Red light or approaching vehicle. Stop before the curb and wait", "Wrist cue W3 means emergency stop. Stop immediately and wait for speech guidance."
        center_road = self._region(scene, "road_or_asphalt", "center", 0.08)
        if center_road and self._dominant_center_road(scene, 0.08) and scene.user_intent != "cross":
            return "Roadway hazard ahead. Stop immediately and reconfirm your direction", "Wrist cue W3 means emergency stop. Speech guides you back to the sidewalk or tactile paving."
        if scene.transit_cue and scene.transit_cue.stop_name and scene.user_intent == "transit":
            cue = scene.transit_cue
            distance = f"{cue.distance_m:.0f} m" if cue.distance_m is not None else "ahead"
            return f"Transit navigation: {cue.stop_name} to the {cue.direction}, about {distance}", cue.next_action or "Follow a safe path to the stop and confirm the stop sign."
        if scene.scene_type == "indoor":
            return scene.scene_label or "Indoor scene", "No crossing or vehicle hazard detected. Provide a brief scene summary."
        if scene.scene_type == "street":
            return "Roadside scene. Stay on the sidewalk or safe side", "Crossing intent is unconfirmed. Traffic-light waiting prompts remain inactive."
        if scene.user_intent == "cross":
            return "Crossing scene detected. Stop before the curb and check vehicles and signals", "D1-D4 indicate approach distance. A red light or approaching vehicle escalates to a W warning cue."
        if scene.tactile_blocked:
            return "Tactile paving blocked. Step left around the obstruction, then continue straight", "Wrist cue W1 indicates a hazard. Slow down and go around it."
        if self._region(scene, "road_or_asphalt", "right", 0.08) and (
            self._region(scene, "walkable_pavement", None, 0.08) or self._region(scene, "tactile_paving", None, 0.02)
        ):
            return "Continue along the sidewalk. Avoid entering the roadway on the right", "Roadway boundary on the right. D1 indicates a low-risk approach. Stay on the safe side."
        if scene.target_query:
            finding = FindingAgent().analyze(scene)
            return finding.status, finding.recommendation
        return "The path ahead appears clear. Continue along the tactile paving", f"{priority.agent_name}: {priority.recommendation}."

    def _compose_voice(self, scene: SceneState, priority: AgentResult) -> str:
        if priority.severity == "danger":
            return priority.recommendation
        if scene.target_query and priority.agent_id in {"finding", "intent"}:
            return FindingAgent().analyze(scene).recommendation
        if priority.severity == "warn":
            return priority.recommendation
        if scene.transit_cue and scene.transit_cue.stop_name and scene.user_intent == "transit":
            return scene.transit_cue.next_action or f"Go to {scene.transit_cue.stop_name}."
        if scene.scene_type == "indoor":
            return scene.scene_description or f"{scene.scene_label or 'Indoor scene'}."
        if scene.scene_type == "street":
            return scene.scene_description or "Roadside scene. Stay on the safe side."
        if scene.user_intent == "cross":
            return "Switched to road crossing. Check traffic signals and vehicles."
        if scene.target_query:
            return FindingAgent().analyze(scene).recommendation
        return "Continue straight."

    def _plan_haptics(self, scene: SceneState, results: list[AgentResult]) -> list[HapticCue]:
        if (scene.traffic_light == "red" and scene.traffic_confidence >= 0.65) or (
            scene.vehicle_approaching and scene.vehicle_confidence >= 0.65
        ):
            return [
                HapticCue("bracelet", "W3", 10, 100, "danger", "Emergency stop: one strong 1-second pulse followed by four rapid short pulses"),
            ]
        center_road = self._region(scene, "road_or_asphalt", "center", 0.14)
        if center_road and center_road.confidence >= 0.65 and self._dominant_center_road(scene, 0.14) and scene.user_intent != "cross":
            return [
                HapticCue("bracelet", "W3", 10, 100, "danger", "Emergency stop: roadway hazard. Stop now"),
            ]
        if scene.tactile_blocked and scene.tactile_confidence >= 0.55:
            return [
                HapticCue("bracelet", "W1", 8, 90, "warn", "Hazard warning: two strong short pulses"),
            ]
        if any(result.severity == "danger" and result.confidence >= 0.6 for result in results):
            return [
                HapticCue("bracelet", "W1", 8, 90, "warn", "Hazard warning: two strong short pulses"),
            ]
        distance = scene.obstacle_distance_m
        has_explicit_obstacle = distance is not None
        if scene.depth_estimate and scene.depth_estimate.center_depth_m is not None:
            if distance is not None or scene.depth_estimate.confidence >= 0.65:
                distance = scene.depth_estimate.center_depth_m if distance is None else min(distance, scene.depth_estimate.center_depth_m)
        obstacle_confidence = max(
            scene.obstacle_confidence,
            scene.depth_estimate.confidence if scene.depth_estimate else 0.0,
        )
        if distance is not None and obstacle_confidence < 0.55:
            return []
        if distance is not None and distance < 0.8:
            return [
                HapticCue("bracelet", "D4", 4, 70, "warn", "Very close: rapid medium-strength short pulses. Stop or slow down"),
            ]
        if distance is not None and distance <= 1.5:
            return [
                HapticCue("bracelet", "D3", 2, 60, "warn", "Close: one medium-strength short pulse every 0.5 seconds"),
            ]
        if distance is not None and distance <= 3.0:
            return [
                HapticCue("bracelet", "D2", 1, 35, "warn", "Medium-distance approach: one light short pulse every second"),
            ]
        if has_explicit_obstacle and distance is not None and distance <= 5.0 and obstacle_confidence >= 0.7:
            return [
                HapticCue("bracelet", "D1", 1, 25, "info", "Distant approach: one light short pulse every 2 seconds"),
            ]
        return []

    def _plan_spatial_audio(self, scene: SceneState, priority: AgentResult) -> list[SpatialAudioCue]:
        cues: list[SpatialAudioCue] = []
        nearest = min(
            scene.detected_objects,
            key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
            default=None,
        )
        if nearest and nearest.distance_m is not None and nearest.distance_m <= 3.2:
            azimuth = {"left": -45, "center": 0, "right": 45, "unknown": 0}[nearest.direction]
            severity = "danger" if nearest.distance_m <= 1.5 else "warn"
            cues.append(
                SpatialAudioCue(
                    direction=nearest.direction,
                    azimuth_deg=azimuth,
                    message=f"{nearest.label} to the {nearest.direction}, about {nearest.distance_m:.1f} m away",
                    priority=severity,
                    volume=1.0 if severity == "danger" else 0.82,
                )
            )
        if scene.transit_cue and scene.transit_cue.direction != "unknown":
            azimuth = {"left": -60, "center": 0, "right": 60, "unknown": 0}[scene.transit_cue.direction]
            cues.append(
                SpatialAudioCue(
                    direction=scene.transit_cue.direction,
                    azimuth_deg=azimuth,
                    message=scene.transit_cue.next_action or f"{scene.transit_cue.stop_name or 'Transit destination'} to the {scene.transit_cue.direction}",
                    priority="info",
                    volume=0.65,
                )
            )
        right_road = self._region(scene, "road_or_asphalt", "right", 0.08)
        if not cues and right_road:
            cues.append(
                SpatialAudioCue(
                    direction="right",
                    azimuth_deg=60,
                    message="Roadway boundary on the right",
                    priority="info",
                    volume=0.55,
                )
            )
        if not cues and priority.severity in {"danger", "warn"}:
            cues.append(SpatialAudioCue("center", 0, priority.recommendation, priority.severity, 0.85))
        return cues

    def _plan_avoidance(self, scene: SceneState) -> AvoidancePlan:
        depth = scene.depth_estimate
        if scene.vehicle_approaching or scene.traffic_light == "red":
            return AvoidancePlan("stop", 0, "High traffic risk. Stop and wait", 0.92)
        if self._dominant_center_road(scene, 0.08) and scene.user_intent != "cross":
            return AvoidancePlan("stop", 0, "Roadway hazard in the center. Stop first and return to the sidewalk", 0.88)
        if depth and depth.center_depth_m is not None and depth.center_depth_m <= 1.5:
            return AvoidancePlan("stop", 0, f"Center depth is only {depth.center_depth_m:.1f} m", depth.confidence)
        if scene.obstacle_distance_m is not None and scene.obstacle_distance_m <= 1.5:
            return AvoidancePlan("stop", 0, f"Obstacle {scene.obstacle_distance_m:.1f} m away", scene.obstacle_confidence)
        if depth and depth.left_clearance_m is not None and depth.right_clearance_m is not None:
            if depth.left_clearance_m - depth.right_clearance_m > 0.8:
                if self._region(scene, "road_or_asphalt", "left", 0.08):
                    return AvoidancePlan("slow_down", 0, "Roadway hazard on the left. Avoid a left detour", depth.confidence)
                return AvoidancePlan("veer_left", -20, "More walkable space on the left", depth.confidence)
            if depth.right_clearance_m - depth.left_clearance_m > 0.8:
                if self._region(scene, "road_or_asphalt", "right", 0.08):
                    return AvoidancePlan("slow_down", 0, "Roadway hazard on the right. Stay on the inner sidewalk", depth.confidence)
                return AvoidancePlan("veer_right", 20, "More walkable space on the right", depth.confidence)
        if scene.tactile_blocked:
            return AvoidancePlan("slow_down", -15, "Tactile paving blocked. Take a short detour and return to it", 0.82)
        if scene.obstacle_distance_m is not None and scene.obstacle_distance_m <= 3.0:
            return AvoidancePlan("slow_down", 0, "Medium-distance obstacle ahead. Reduce speed", scene.obstacle_confidence)
        return AvoidancePlan("proceed", 0, "Current path risk is low", 0.78)

    def _region(self, scene: SceneState, label: str, direction: str | None, min_coverage: float):
        candidates = [
            region
            for region in scene.semantic_regions
            if region.label == label and (direction is None or region.direction == direction) and region.coverage >= min_coverage
        ]
        return max(candidates, key=lambda region: region.coverage, default=None)

    def _dominant_center_road(self, scene: SceneState, min_coverage: float) -> bool:
        road = self._region(scene, "road_or_asphalt", "center", min_coverage)
        if not road:
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

    def _with_agent_focus(self, result: AgentResult, scene: SceneState) -> AgentResult:
        focus = self._agent_focus(result.agent_id, scene)
        return replace(result, focus=focus)

    def _agent_focus(self, agent_id: str, scene: SceneState) -> str:
        nearest = self._nearest_object(scene)
        if agent_id == "obstacle":
            if nearest:
                return f"Focus: nearest object {_object_text(nearest)}"
            if scene.obstacle_distance_m is not None:
                return f"Focus: center-path obstacle {scene.obstacle_distance_m:.1f} m away"
            return "Focus: obstruction of the center path"
        if agent_id == "tactile":
            tactile = self._region(scene, "tactile_paving", None, 0.0)
            if tactile:
                return f"Focus: {_region_text(tactile)}"
            return "Focus: tactile paving continuity and obstruction"
        if agent_id == "object":
            if scene.detected_objects:
                objects = ", ".join(_object_text(obj) for obj in scene.detected_objects[:3])
                return f"Focus: {objects}"
            return "Focus: pedestrians, vehicles, bicycles and obstacles"
        if agent_id == "depth":
            depth = scene.depth_estimate
            if depth and depth.center_depth_m is not None:
                return f"Focus: depth ahead {depth.center_depth_m:.1f} m and left/right clearance"
            return "Focus: center depth and left/right clearance"
        if agent_id == "semantic":
            regions = self._top_regions(scene, limit=3)
            if regions:
                return "Focus: " + ", ".join(_region_text(region) for region in regions)
            return "Focus: walkable areas, roadway, vegetation and tactile paving"
        if agent_id == "route":
            walkable = self._region(scene, "walkable_pavement", None, 0.02) or self._region(scene, "tactile_paving", None, 0.0)
            road = self._region(scene, "crosswalk", None, 0.006) or self._region(scene, "road_or_asphalt", None, 0.02)
            parts = [item for item in (_region_text(walkable) if walkable else "", _region_text(road) if road else "") if item]
            return "Focus: " + (", ".join(parts) if parts else "safe path and roadway boundary")
        if agent_id == "avoidance":
            if nearest:
                return f"Focus: {_object_text(nearest)} and left/right avoidance space"
            return "Focus: active avoidance direction and available detour space"
        if agent_id == "traffic":
            light = "No traffic light detected" if scene.traffic_light == "unknown" else f"Traffic light: {scene.traffic_light}"
            return f"Focus: {light}"
        if agent_id == "crossing":
            road = self._region(scene, "road_or_asphalt", None, 0.02)
            road_text = _region_text(road) if road else "roadway/crosswalk area"
            return f"Focus: {road_text}, approaching vehicles and traffic signals"
        if agent_id == "spatial_audio":
            if nearest:
                return f"Focus: spatial audio {_object_label(nearest.label)} {DIRECTION_LABELS[nearest.direction]}"
            return "Focus: direction of the hazard"
        if agent_id == "finding":
            if scene.target_query:
                direction = DIRECTION_LABELS.get(scene.target_direction) if scene.target_direction != "unknown" and scene.target_confidence >= 0.5 else None
                return f"Focus: find {scene.target_query}" + (f" {direction}" if direction else "")
            return "Focus: user-specified target object"
        if agent_id == "transit":
            if scene.transit_cue and scene.transit_cue.stop_name:
                return f"Focus: {scene.transit_cue.stop_name} and the stop sign direction"
            return "Focus: transit stops, stop signs and route text"
        if agent_id == "scene":
            regions = self._top_regions(scene, limit=4)
            if regions:
                return "Focus: overall segmented scene, " + ", ".join(_region_text(region) for region in regions)
            return "Focus: overall description of the segmented scene"
        if agent_id == "text":
            return "Focus: " + (", ".join(scene.detected_texts[:3]) if scene.detected_texts else "street text, building numbers and notices")
        if agent_id == "sign":
            return "Focus: " + (", ".join(scene.sign_candidates[:2]) if scene.sign_candidates else "storefront signs and entrance markers")
        if agent_id == "intent":
            label = scene.scene_label or scene.scene_type
            return f"Focus: current scene {label} and user intent {scene.user_intent}"
        return "Focus: perception cues relevant to the current task"

    def _nearest_object(self, scene: SceneState):
        return min(
            scene.detected_objects,
            key=lambda obj: obj.distance_m if obj.distance_m is not None else 99.0,
            default=None,
        )

    def _top_regions(self, scene: SceneState, limit: int = 3):
        return sorted(scene.semantic_regions, key=lambda region: region.coverage, reverse=True)[:limit]

    def _estimate_cognitive_load(self, results: list[AgentResult]) -> dict[str, int]:
        # Legacy method kept for backward compatibility: delegates to new L-score method
        return self._compute_cognitive_load(results, None, len(results))  # type: ignore[arg-type]


def _region_text(region) -> str:
    direction = DIRECTION_LABELS.get(region.direction, "nearby")
    label = REGION_LABELS.get(region.label, region.label.replace("_", " "))
    return f"{label} {direction}, {round(region.coverage * 100)}% coverage"


def _object_text(obj) -> str:
    direction = DIRECTION_LABELS.get(obj.direction, "nearby")
    distance = f"{obj.distance_m:.1f} m" if obj.distance_m is not None else "distance unknown"
    return f"{_object_label(obj.label)} {direction}, {distance}"


def _object_label(label: str) -> str:
    return OBJECT_LABELS.get(label, label.replace("_", " "))
