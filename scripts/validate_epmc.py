#!/usr/bin/env python3
"""Reproducible Algorithm 1 validation and synthetic software replay.

This is not a participant study or a physical output latency measurement.
Run from any working directory. Optional --json writes the software results.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(REPOSITORY))

from libereye.coordination_evaluation import CoordinationEvaluator
from libereye.epmc import EPMCCoordinator
from libereye.wrist_haptics import WRIST_CUE_PRIORITY_ORDER


def verify_algorithm() -> int:
    """Exhaust all cue subsets, override, severity and gate inputs."""
    coordinator = EPMCCoordinator()
    cues = WRIST_CUE_PRIORITY_ORDER
    count = 0
    for included in itertools.product((False, True), repeat=len(cues)):
        candidates = [cue for cue, use in zip(cues, included) if use]
        for override, severity, changed, requested in itertools.product((False, True), ("info", "warn", "danger"), (False, True), (False, True)):
            result = coordinator.coordinate(candidates, override, severity, changed, requested)
            expected_cue = "W3" if override else next(iter(candidates), None)
            blocked = expected_cue in {"W1", "W2", "W3", "D4"} or severity == "danger"
            if result.wrist_cue != expected_cue or result.description_blocked != blocked or result.description_gate != (not blocked and (changed or requested)) or not result.action_instruction:
                raise AssertionError((candidates, override, severity, changed, requested, result))
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, dest="json_path", help="Write a JSON software validation report")
    args = parser.parse_args()
    count = verify_algorithm()
    results = CoordinationEvaluator().evaluate_benchmark_scenarios()
    report = {
        "algorithm_cases_passed": count,
        "input_kind": "synthetic_scene_fixtures",
        "physical_output_measured": False,
        "human_study_metrics": None,
        "conditions": {condition: asdict(metrics) for condition, metrics in results.items()},
    }
    print(f"Algorithm 1 and empty-candidate extension: {count} cases passed")
    print("Synthetic software replay; times exclude network, BLE, TTS and motor response.")
    print("Condition | Frames | Suppressions | Preemptions | Cues planned | Median processing ms | P95 processing ms")
    for condition, metrics in results.items():
        print(f"{condition} | {metrics.total_frames} | {metrics.speech_suppressions} | {metrics.haptic_preemptions} | {metrics.total_cues_emitted} | {metrics.median_latency_ms:.4f} | {metrics.p95_latency_ms:.4f}")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {args.json_path}")


if __name__ == "__main__":
    main()
