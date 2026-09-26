#!/usr/bin/env python3
"""Batch E2E test runner for mock mobile client scenarios."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from e2e_test_client import MobileClient  # noqa: E402


@dataclass
class TestResult:
    scenario_name: str
    passed: bool
    latency_ms: float
    errors: list[str]
    actual: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None


def load_scenario(scenario_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    input_path = scenario_dir / "input.jpg"
    expected_path = scenario_dir / "expected.json"
    if not input_path.exists() or not expected_path.exists():
        return None
    return input_path, json.loads(expected_path.read_text(encoding="utf-8"))


def validate_result(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if actual.get("priority") != expected.get("priority"):
        errors.append(f"priority expected {expected.get('priority')}, got {actual.get('priority')}")
    if "voice_message_contains" in expected and expected["voice_message_contains"] not in actual.get("voice_message", ""):
        errors.append(f"voice_message missing {expected['voice_message_contains']!r}")
    if actual.get("vision_backend") != expected.get("vision_backend"):
        errors.append(f"vision_backend expected {expected.get('vision_backend')}, got {actual.get('vision_backend')}")
    if actual.get("should_speak") is not expected.get("should_speak"):
        errors.append(f"should_speak expected {expected.get('should_speak')}, got {actual.get('should_speak')}")
    bracelet = actual.get("bracelet")
    if expected.get("bracelet_required") and not bracelet:
        errors.append("bracelet cue required but missing")
    if bracelet and "bracelet_pattern" in expected and bracelet.get("pattern") != expected["bracelet_pattern"]:
        errors.append(f"bracelet pattern expected {expected['bracelet_pattern']}, got {bracelet.get('pattern')}")
    if not actual.get("voice_message"):
        errors.append("voice_message is empty")
    return errors


def run_e2e_tests(cloud_url: str, fixtures_dir: Path, timeout: float = 5.0) -> list[TestResult]:
    client = MobileClient(cloud_url, timeout=timeout)
    results: list[TestResult] = []
    scenario_dirs = sorted(path for path in fixtures_dir.iterdir() if path.is_dir()) if fixtures_dir.exists() else []

    for scenario_dir in scenario_dirs:
        scenario = load_scenario(scenario_dir)
        if scenario is None:
            print(f"[SKIP] {scenario_dir.name}: missing input.jpg or expected.json")
            continue
        input_path, expected = scenario
        print(f"[TEST] {scenario_dir.name}...", end=" ")
        start = time.perf_counter()
        try:
            actual = client.process_frame(input_path)
            latency_ms = (time.perf_counter() - start) * 1000.0
            errors = validate_result(actual, expected)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            actual = None
            errors = [f"exception: {exc}"]
        passed = not errors
        results.append(TestResult(scenario_dir.name, passed, latency_ms, errors, actual, expected))
        print(f"{'PASS' if passed else 'FAIL'} ({latency_ms:.1f}ms)")
        for error in errors:
            print(f"  - {error}")
    return results


def print_summary(results: list[TestResult]) -> None:
    total = len(results)
    passed = sum(result.passed for result in results)
    failed = total - passed
    print()
    print("=" * 60)
    print("E2E Test Summary")
    print("=" * 60)
    print(f"Total: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    if results:
        avg_latency = sum(result.latency_ms for result in results) / total
        print(f"Average software request and mock-dispatch duration: {avg_latency:.1f}ms")
    if failed:
        print()
        print("Failed scenarios:")
        for result in results:
            if result.passed:
                continue
            print(f"  - {result.scenario_name}")
            for error in result.errors:
                print(f"    {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mock mobile E2E scenarios")
    parser.add_argument("--cloud-url", default="http://127.0.0.1:8080")
    parser.add_argument("--fixtures-dir", type=Path, default=Path(__file__).parent.parent / "tests" / "fixtures" / "e2e")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    results = run_e2e_tests(args.cloud_url, args.fixtures_dir, args.timeout)
    print_summary(results)
    return 0 if results and all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
