from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .models import AssistancePlan
from .mobile_contract import vision_backend_label
from .wrist_haptics import WRIST_PROTOCOL, encode_wrist_command, wrist_timing_profile


def format_smartphone_plan(
    plan: AssistancePlan,
    evidence: Optional[Dict[str, Any]] = None,
    source: str = "phone_media",
    glasses_connected: Optional[bool] = None,
    wrist_connected: Optional[bool] = True,
) -> Dict[str, Any]:
    """Formats the AssistancePlan for smartphone execution (Section 2.1, 2.2).

    The smartphone executes the assistance plan through text-to-speech (TTS)
    and Bluetooth Low Energy (BLE) wrist commands.
    """
    evidence = evidence or {}
    cue = plan.haptics[0] if plan.haptics else None

    # Section 2.2, Line 10 keeps concise action guidance eligible for speech.
    spoken_text = plan.voice_message

    # Fallback interaction: if wristband is disconnected, available speech conveys wrist warnings
    fallback_messages: List[str] = []
    if wrist_connected is False and cue:
        fallback_warning = f"[Haptic fallback speech] {cue.meaning}"
        spoken_text = f"{fallback_warning}. {spoken_text}"
        fallback_messages.append(fallback_warning)

    # Smartphone executable actions (TTS, BLE, UI)
    output_actions: List[Dict[str, Any]] = []

    # 1. BLE Wrist command (if cue selected and wristband connected)
    if cue and wrist_connected is not False:
        output_actions.append(
            {
                "type": "ble_haptic",
                "device": cue.device,
                "pattern": cue.pattern,
                "intensity": cue.intensity,
                "frequency_hz": cue.frequency_hz,
                "risk_level": cue.risk_level,
                "meaning": cue.meaning,
                "command": cue.pattern,
                "command_bytes": list(encode_wrist_command(cue.pattern)),
                "protocol": WRIST_PROTOCOL,
                "duration_ms": 3000,
                "timing_profile": wrist_timing_profile(cue.pattern),
            }
        )

    # 2. TTS Voice dispatch
    should_speak = plan.context_plan.should_speak or bool(fallback_messages)
    if spoken_text and should_speak:
        output_actions.append(
            {
                "type": "tts",
                "message": spoken_text,
                "priority": plan.priority,
                "interrupt": plan.priority in {"warn", "danger"},
            }
        )

    # 3. UI Status for VoiceOver
    output_actions.append(
        {
            "type": "ui_status",
            "priority": plan.priority,
            "main_instruction": plan.main_instruction,
            "secondary_instruction": plan.secondary_instruction,
            "wrist_cue": plan.wrist_cue,
            "description_gate": plan.description_gate,
        }
    )

    payload: Dict[str, Any] = {
        "source": source,
        "priority": plan.priority,
        "main_instruction": plan.main_instruction,
        "secondary_instruction": plan.secondary_instruction,
        "voice_message": spoken_text,
        "wrist_cue": plan.wrist_cue,
        "description_gate": plan.description_gate,
        "description_blocked": plan.description_blocked,
        "action_instruction": plan.action_instruction,
        "eligible_scene_description": plan.eligible_scene_description,
        "bracelet": asdict(cue) if cue else None,
        "output_actions": output_actions,
        "spatial_audio": [asdict(item) for item in plan.spatial_audio],
        "avoidance_plan": asdict(plan.avoidance_plan),
        "transit_cue": asdict(plan.transit_cue) if plan.transit_cue else None,
        "should_speak": should_speak,
        "context_reasoning": plan.context_plan.reasoning_summary,
        "reminder_trigger": plan.context_plan.reminder_trigger,
        "cognitive_load": plan.cognitive_load,
        "safety_notes": plan.safety_notes,
        "metadata": plan.metadata,
        "speech_suppressions": plan.metadata.get("speech_suppression_count", 0),
        "haptic_preemptions": plan.metadata.get("haptic_preemption_count", 0),
        "scene_brief": plan.main_instruction,
        "risk_brief": "High risk" if plan.priority == "danger" else ("Caution" if plan.priority == "warn" else "Proceed normally"),
        "next_action": plan.action_instruction,
        "perception_evidence": evidence,
        "vision_backend": vision_backend_label(evidence),
        "vision_backend_status": evidence.get("vision_backend"),
        "scene_type": evidence.get("scene_type") or plan.metadata.get("fsm_phase"),
        "scene_label": evidence.get("scene_label"),
        "scene_description": evidence.get("scene_description"),
        "glasses_description": evidence.get("glasses_description"),
        "scene_switch_message": evidence.get("scene_switch_message"),
        "detected_objects": evidence.get("detected_objects", []),
        "semantic_regions": evidence.get("semantic_regions", []),
        "depth_estimate": evidence.get("depth_estimate"),
        "detected_texts": evidence.get("detected_texts", []),
        "sign_candidates": evidence.get("sign_candidates", []),
        "agent_summary": [
            {"agent": result.agent_name, "agent_id": result.agent_id,
             "severity": result.severity, "priority": result.priority,
             "status": result.status, "focus": result.focus}
            for result in plan.agent_results
        ],
    }

    if glasses_connected is not None:
        payload["glasses_connected"] = glasses_connected
    if wrist_connected is not None:
        payload["wrist_connected"] = wrist_connected

    return payload


# Backwards compatibility alias for mobile_contract.py
def mobile_response(
    plan: AssistancePlan,
    evidence: Optional[Dict[str, Any]] = None,
    source: str = "phone",
    glasses_connected: Optional[bool] = None,
    wrist_connected: Optional[bool] = True,
) -> Dict[str, Any]:
    return format_smartphone_plan(
        plan=plan,
        evidence=evidence,
        source=source,
        glasses_connected=glasses_connected,
        wrist_connected=wrist_connected,
    )


def perception_evidence(payload: Dict[str, Any], source: str = "structured") -> Dict[str, Any]:
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
