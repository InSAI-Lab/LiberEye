from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any

from .models import AssistancePlan


def vision_backend_label(evidence: dict[str, Any] | None) -> str:
    if not evidence:
        return "structured"
    backend_status = evidence.get("vision_backend")
    if isinstance(backend_status, dict):
        return "ultralytics" if backend_status.get("active") else "heuristic"
    if isinstance(backend_status, str) and backend_status:
        return backend_status
    return "heuristic"


def mobile_response(
    plan: AssistancePlan,
    evidence: dict[str, Any] | None = None,
    source: str = "phone",
    glasses_connected: bool | None = None,
    wrist_connected: bool | None = True,
) -> dict[str, Any]:
    """Compact contract consumed by the mobile app.

    This is the boundary between LiberEye's internal multi-agent plan and the
    app's output devices: TTS, bracelet BLE, spatial audio, and screen UI.
    """
    if plan.metadata.get("coordinator") == "epmc":
        # Preserve Algorithm 1's admitted speech. Rebuilding a spoken summary
        # from raw evidence would reintroduce descriptions suppressed by EPMC.
        from .smartphone_relay import format_smartphone_plan
        return format_smartphone_plan(plan, evidence, source, glasses_connected, wrist_connected)
    evidence = evidence or {}
    cue = plan.haptics[0] if plan.haptics else None
    scene_brief = _scene_brief(plan, evidence)
    risk_brief = _risk_brief(plan, cue)
    next_action = _next_action(plan)
    spoken_summary = _spoken_summary(scene_brief, risk_brief, next_action)
    output_actions = _output_actions(plan, cue, spoken_summary)
    payload: dict[str, Any] = {
        "source": source,
        "priority": plan.priority,
        "main_instruction": plan.main_instruction,
        "secondary_instruction": plan.secondary_instruction,
        "voice_message": spoken_summary,
        "scene_brief": scene_brief,
        "risk_brief": risk_brief,
        "next_action": next_action,
        "bracelet": asdict(cue) if cue else None,
        "output_actions": output_actions,
        "spatial_audio": [asdict(item) for item in plan.spatial_audio],
        "avoidance_plan": asdict(plan.avoidance_plan),
        "transit_cue": asdict(plan.transit_cue) if plan.transit_cue else None,
        "context_reasoning": plan.context_plan.reasoning_summary,
        "reminder_trigger": plan.context_plan.reminder_trigger,
        "should_speak": plan.context_plan.should_speak,
        "cognitive_load": plan.cognitive_load,
        "safety_notes": plan.safety_notes,
        "metadata": plan.metadata,
        "wrist_cue": plan.wrist_cue or (cue.pattern if cue else None),
        "description_gate": plan.description_gate,
        "description_blocked": plan.description_blocked,
        "action_instruction": plan.action_instruction or plan.main_instruction,
        "eligible_scene_description": plan.eligible_scene_description,
        "scene_description": evidence.get("scene_description"),
        "glasses_description": evidence.get("glasses_description"),
        "scene_type": evidence.get("scene_type") or _metadata_scene_type(plan),
        "scene_label": evidence.get("scene_label"),
        "scene_switch_message": evidence.get("scene_switch_message"),
        "detected_objects": evidence.get("detected_objects", []),
        "semantic_regions": evidence.get("semantic_regions", []),
        "depth_estimate": evidence.get("depth_estimate"),
        "vision_backend": vision_backend_label(evidence),
        "vision_backend_status": evidence.get("vision_backend"),
        "detected_texts": evidence.get("detected_texts", []),
        "sign_candidates": evidence.get("sign_candidates", []),
        "agent_summary": [
            {
                "agent": result.agent_name,
                "agent_id": result.agent_id,
                "severity": result.severity,
                "priority": result.priority,
                "status": result.status,
                "focus": result.focus,
            }
            for result in plan.agent_results
        ],
    }
    if glasses_connected is not None:
        payload["glasses_connected"] = glasses_connected
    return payload


def perception_evidence(payload: dict[str, Any], source: str = "structured") -> dict[str, Any]:
    """Build lightweight evidence when the app sends already-normalized perception.

    This path is useful when the phone app has already called Doubao or another
    model and only needs LiberEye's multi-agent safety fusion.
    """
    return {
        "vision_backend": source,
        "scene_type": payload.get("scene_type"),
        "scene_label": payload.get("scene_label"),
        "scene_description": payload.get("scene_description"),
        "detected_objects": payload.get("detected_objects", []),
        "semantic_regions": payload.get("semantic_regions", []),
        "depth_estimate": payload.get("depth_estimate"),
        "detected_texts": payload.get("detected_texts", []),
        "sign_candidates": payload.get("sign_candidates", []),
    }


def _metadata_scene_type(plan: AssistancePlan) -> str | None:
    state = plan.metadata.get("fsm_state")
    return state if isinstance(state, str) else None


def _output_actions(plan: AssistancePlan, cue: Any | None, spoken_summary: str) -> list[dict[str, Any]]:
    """Return app-executable actions for TTS, BLE haptics, and screen status."""
    actions: list[dict[str, Any]] = []
    if cue and plan.priority in {"warn", "danger"}:
        actions.append(
            {
                "type": "ble_haptic",
                "device": cue.device,
                "pattern": cue.pattern,
                "intensity": cue.intensity,
                "risk_level": cue.risk_level,
                "meaning": cue.meaning,
                "command": f"{cue.pattern}:{cue.intensity}",
            }
        )
    if spoken_summary and plan.context_plan.should_speak:
        actions.append(
            {
                "type": "tts",
                "message": spoken_summary,
                "priority": plan.priority,
                "interrupt": plan.priority in {"warn", "danger"},
            }
        )
    actions.append(
        {
            "type": "ui_status",
            "priority": plan.priority,
            "main_instruction": plan.main_instruction,
            "secondary_instruction": plan.secondary_instruction,
            "scene_brief": _compact(plan.main_instruction, 120),
        }
    )
    return actions


def _scene_brief(plan: AssistancePlan, evidence: dict[str, Any]) -> str:
    description = evidence.get("scene_description")
    if isinstance(description, str) and description.strip():
        first_sentence = re.split(r"(?<=[.!?])\s+", description.strip(), maxsplit=1)[0]
        return _compact(first_sentence, 120)
    scene_label = evidence.get("scene_label")
    if isinstance(scene_label, str) and scene_label:
        return _compact(scene_label, 64)
    scene_type = evidence.get("scene_type") or _metadata_scene_type(plan)
    labels = {
        "sidewalk": "Sidewalk",
        "street": "Roadside",
        "crossing": "Crossing scene",
        "blocked": "Path obstructed",
        "finding": "Searching for the target",
        "transit": "Transit navigation",
        "indoor": "Indoor scene",
    }
    return labels.get(scene_type, "Scene unclear")


def _risk_brief(plan: AssistancePlan, cue: Any | None) -> str:
    if plan.priority == "danger":
        return "High risk"
    if plan.priority == "warn":
        return "Caution"
    if cue:
        return "Low-risk approach"
    return "No obvious hazard detected"


def _next_action(plan: AssistancePlan) -> str:
    text = plan.voice_message or plan.main_instruction
    replacements = {
        "Stop immediately and replan": "Stop now",
        "Stop and confirm the avoidance direction": "Stop and check the detour",
        "Stop and wait": "Stop and wait",
        "Slow down and look for more open space": "Slow down and check both sides",
        "Slow down and maintain lateral clearance": "Slow down and keep your distance",
        "Continue along the walkable area": "Continue straight",
        "Continue forward": "Continue straight",
    }
    for source, target in replacements.items():
        if source in text:
            return target
    text = re.split(r"(?<=[.!?])\s+|[,;]\s+", text, maxsplit=1)[0]
    return _compact(text, 120)


def _spoken_summary(scene: str, risk: str, action: str) -> str:
    parts = [part.rstrip(". ") for part in [scene, risk, action] if part]
    return ". ".join(parts[:3]) + "."


def _compact(text: str, limit: int) -> str:
    text = " ".join(str(text).replace("\n", " ").split()).strip(" .")
    if len(text) <= limit:
        return text
    prefix = text[: limit - 3].rsplit(" ", 1)[0]
    return prefix + "..."
