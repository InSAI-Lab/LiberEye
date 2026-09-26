from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libereye.models import PerceptionFrame
from libereye.runtime import MobilityRuntime


def main() -> None:
    runtime = MobilityRuntime()
    frames = [
        PerceptionFrame(obstacle_distance_m=4.0, obstacle_confidence=0.92),
        PerceptionFrame(obstacle_distance_m=2.4, obstacle_confidence=0.88, tactile_blocked=True, tactile_confidence=0.86),
        PerceptionFrame(
            traffic_light="green",
            traffic_confidence=0.91,
            user_intent="cross",
            vehicle_approaching=True,
            vehicle_confidence=0.89,
        ),
        PerceptionFrame(sensor_health="lost"),
    ]

    for frame in frames:
        plan = runtime.process_frame(frame)
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
