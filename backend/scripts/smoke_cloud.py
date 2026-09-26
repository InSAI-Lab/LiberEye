"""Authenticated smoke check; does not print credentials or camera contents."""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import uuid

from dotenv import load_dotenv
import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    token = os.getenv("LIBEREYE_API_TOKEN")
    if not token:
        raise SystemExit("Configure LIBEREYE_API_TOKEN before running the smoke check")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "X-LiberEye-Session": str(uuid.uuid4())})
    base = args.base_url.rstrip("/")
    for path in ("/health", "/ready"):
        response = session.get(base + path, timeout=15)
        response.raise_for_status()
    response = session.post(base + "/api/mobile/analyze-perception", params={"detail_request": "true"}, json={
        "scene_type": "crossing", "traffic_light": "red", "traffic_confidence": 0.95,
        "scene_description": "optional test detail", "user_intent": "cross",
    }, timeout=15)
    response.raise_for_status()
    plan = response.json()
    if plan["wrist_cue"] != "W3" or plan["description_gate"] or "optional test detail" in plan["voice_message"]:
        raise SystemExit("FAILED: stop override or speech gate does not match the EPMC contract")
    actions = plan["output_actions"]
    if not actions or actions[0]["type"] != "ble_haptic" or actions[0]["command_bytes"][0] != 7:
        raise SystemExit("FAILED: missing binary W3 haptic action")
    print("PASS: liveness, readiness, authenticated EPMC stop, description gate and BLE command")


if __name__ == "__main__":
    main()
