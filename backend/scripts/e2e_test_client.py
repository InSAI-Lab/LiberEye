#!/usr/bin/env python3
"""Mock mobile client for E2E testing.

The client simulates the iOS relay app: upload a frame to the cloud API, play
the returned voice message, dispatch haptics for warning/danger plans, and fall
back to a fixed connection-loss stop notice when the cloud request fails.
It performs no local inference and measures no physical output delivery.
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.HTTPStatusError,
    httpx.NetworkError,
)


@dataclass
class MockEarphone:
    """Simulates bone-conduction headphone TTS output."""

    def play_tts(self, message: str) -> None:
        print(f"[EARPHONE] TTS: {message}")


@dataclass
class MockBracelet:
    """Simulates bracelet haptic output."""

    def vibrate(self, pattern: str, intensity: int) -> None:
        print(f"[BRACELET] Vibrate: {pattern} intensity={intensity}")


class MobileClient:
    """Mock mobile client with timeout, retry, fallback, and recovery probing."""

    def __init__(self, cloud_url: str, timeout: float | None = None, api_token: str | None = None) -> None:
        self.cloud_url = cloud_url.rstrip("/")
        self.timeout = timeout if timeout is not None else float(os.getenv("LIBEREYE_CLOUD_TIMEOUT", "5.0"))
        self.api_token = api_token or os.getenv("LIBEREYE_API_TOKEN")
        self.earphone = MockEarphone()
        self.bracelet = MockBracelet()
        self.fallback_mode = False
        self.last_health_check = 0.0
        self.health_check_interval = 30.0

    def process_frame(self, image_path: Path, target_query: str | None = None) -> dict[str, Any]:
        """Process one frame or return a fixed unavailable-perception notice."""
        if self.fallback_mode and self._should_probe_health() and self._check_cloud_health():
            self.fallback_mode = False
            print("Network restored")

        if self.fallback_mode:
            plan = self._local_heuristic()
        else:
            plan = self._call_cloud_with_retry(image_path, target_query)

        self._dispatch_outputs(plan)
        return plan

    def _call_cloud_with_retry(self, image_path: Path, target_query: str | None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                plan = self._call_cloud(image_path, target_query)
                self.fallback_mode = False
                return plan
            except RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt == 0:
                    print(f"[WARN] Cloud request failed: {exc}; retrying once")
                    time.sleep(0.1)

        self.fallback_mode = True
        print("Cloud unavailable; stop and confirm surroundings")
        if last_error is not None:
            print(f"[WARN] Cloud request failed ({type(last_error).__name__}); perception unavailable")
        return self._local_heuristic()

    def _call_cloud(self, image_path: Path, target_query: str | None) -> dict[str, Any]:
        """Make a multipart request to the cloud API."""
        with image_path.open("rb") as media_file:
            response = httpx.post(
                f"{self.cloud_url}/api/mobile/analyze-media",
                files={"media": (image_path.name, media_file, "image/jpeg")},
                data={"target_query": target_query} if target_query else {},
                headers=self._auth_headers(),
                timeout=self.timeout,
            )
        response.raise_for_status()
        return response.json()

    def _should_probe_health(self) -> bool:
        return time.time() - self.last_health_check >= self.health_check_interval

    def _check_cloud_health(self) -> bool:
        """Probe authenticated readiness before leaving the unavailable state."""
        self.last_health_check = time.time()
        try:
            response = httpx.get(f"{self.cloud_url}/ready", headers=self._auth_headers(), timeout=2.0)
            return response.status_code == 200 and response.json().get("status") == "ready"
        except httpx.HTTPError:
            return False

    def _dispatch_outputs(self, plan: dict[str, Any]) -> None:
        if "output_actions" in plan:
            for action in plan["output_actions"]:
                if action.get("type") == "tts" and plan.get("should_speak"):
                    self.earphone.play_tts(str(action["message"]))
                elif action.get("type") == "ble_haptic":
                    self.bracelet.vibrate(str(action["pattern"]), int(action.get("intensity", 0)))
            return
        if plan.get("voice_message") and plan.get("should_speak"):
            self.earphone.play_tts(str(plan["voice_message"]))

        bracelet = plan.get("bracelet")
        if bracelet and plan.get("priority") in {"warn", "danger"}:
            self.bracelet.vibrate(str(bracelet.get("pattern", "D1")), int(bracelet.get("intensity", 40)))

    def _local_heuristic(self) -> dict[str, Any]:
        """Legacy method name; return a fixed stop notice without inference."""
        return {
            "priority": "danger",
            "main_instruction": "Stop and confirm your surroundings with your mobility aid.",
            "voice_message": "Perception is unavailable. Stop and confirm your surroundings with your mobility aid.",
            "bracelet": None,
            "spatial_audio": [],
            "avoidance_plan": {
                "action": "stop",
                "heading_delta_deg": 0,
                "rationale": "Cloud perception is unavailable; no scene inference was performed.",
                "confidence": 0.0,
            },
            "transit_cue": None,
            "context_reasoning": "Fixed connection-loss notice, not local inference.",
            "reminder_trigger": "urgent",
            "should_speak": True,
            "scene_description": "Fallback mode.",
            "glasses_description": None,
            "scene_type": "unknown",
            "scene_label": "fallback",
            "scene_switch_message": None,
            "detected_objects": [],
            "semantic_regions": [],
            "depth_estimate": None,
            "vision_backend": "unavailable",
            "detected_texts": [],
            "sign_candidates": [],
            "agent_summary": [],
        }

    def _auth_headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one frame through the mock mobile client")
    parser.add_argument("image_path", type=Path)
    parser.add_argument("cloud_url", nargs="?", default="http://127.0.0.1:8080")
    parser.add_argument("--target-query")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--api-token", default=os.getenv("LIBEREYE_API_TOKEN"))
    args = parser.parse_args()

    client = MobileClient(args.cloud_url, timeout=args.timeout, api_token=args.api_token)
    plan = client.process_frame(args.image_path, target_query=args.target_query)
    print(f"Priority: {plan['priority']}")
    print(f"Backend: {plan.get('vision_backend', 'unknown')}")
    print(f"Fallback mode: {client.fallback_mode}")
    return 1 if client.fallback_mode else 0


if __name__ == "__main__":
    raise SystemExit(main())
