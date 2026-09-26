from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def ensure_e2e_fixtures(base_dir: Path) -> list[dict]:
    """Create deterministic synthetic E2E image fixtures if they are missing."""
    scenarios = {
        "scenario_01_sidewalk_normal": _sidewalk_normal,
        "scenario_02_crossing_red": _crossing_red,
        "scenario_03_tactile_blocked": _tactile_blocked,
    }
    loaded: list[dict] = []
    for name, factory in scenarios.items():
        scenario_dir = base_dir / name
        scenario_dir.mkdir(parents=True, exist_ok=True)
        input_path = scenario_dir / "input.jpg"
        if not input_path.exists():
            temp_path = scenario_dir / "input.tmp.jpg"
            cv2.imwrite(str(temp_path), factory())
            temp_path.replace(input_path)
        expected_path = scenario_dir / "expected.json"
        if expected_path.exists():
            loaded.append(
                {
                    "name": name,
                    "input": input_path,
                    "expected": json.loads(expected_path.read_text(encoding="utf-8")),
                }
            )
    return loaded


def _sidewalk_normal() -> np.ndarray:
    image = np.full((360, 520, 3), 145, dtype=np.uint8)
    cv2.rectangle(image, (0, 180), (519, 359), (165, 165, 165), -1)
    return image


def _crossing_red() -> np.ndarray:
    image = np.full((360, 520, 3), 55, dtype=np.uint8)
    for y in (180, 230, 280):
        cv2.rectangle(image, (35, y), (485, y + 24), (240, 240, 240), -1)
    cv2.circle(image, (430, 70), 22, (0, 0, 255), -1)
    cv2.rectangle(image, (235, 120), (285, 310), (25, 25, 25), -1)
    return image


def _tactile_blocked() -> np.ndarray:
    image = np.full((420, 560, 3), 178, dtype=np.uint8)
    cv2.rectangle(image, (250, 170), (302, 419), (0, 178, 218), -1)
    cv2.rectangle(image, (198, 272), (354, 326), (0, 178, 218), -1)
    cv2.rectangle(image, (215, 300), (345, 380), (30, 30, 30), -1)
    return image
