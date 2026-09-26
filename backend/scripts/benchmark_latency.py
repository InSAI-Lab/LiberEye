#!/usr/bin/env python3
"""HTTP response timings only; excludes BLE, TTS and physical motor response."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from dotenv import load_dotenv


def get_git_commit() -> str:
    """Return the current short git commit hash for reproducibility."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def benchmark_scenario(
    cloud_url: str,
    image_path: Path,
    num_runs: int = 100,
    timeout: float = 10.0,
    api_token: str | None = None,
) -> dict[str, float | int | None]:
    """Measure request latency for one scenario using real HTTP."""
    if num_runs < 1 or timeout <= 0:
        raise ValueError("num_runs and timeout must be positive")
    latencies: list[float] = []
    errors = 0
    token = api_token or os.getenv("LIBEREYE_API_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for _ in range(num_runs):
            start = time.perf_counter()
            try:
                with image_path.open("rb") as media_file:
                    response = client.post(
                        f"{cloud_url.rstrip('/')}/api/mobile/analyze-media",
                        files={"media": (image_path.name, media_file, "image/jpeg")},
                    )
                response.raise_for_status()
            except (OSError, httpx.HTTPError):
                errors += 1
                continue
            end = time.perf_counter()
            latencies.append((end - start) * 1000.0)

    if not latencies:
        return {
            "p50": None,
            "p95": None,
            "p99": None,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "successful_runs": 0,
            "failed_runs": errors,
        }

    values = np.array(latencies, dtype=float)
    return {
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "successful_runs": len(latencies),
        "failed_runs": errors,
    }


def benchmark_cloud_pipeline(
    cloud_url: str,
    fixtures_dir: Path,
    num_runs: int = 100,
    timeout: float = 10.0,
    api_token: str | None = None,
) -> dict[str, Any]:
    """Benchmark all E2E scenario input images."""
    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "cloud_url": cloud_url,
        "num_runs": num_runs,
        "measurement": "http_request_to_response_ms",
        "physical_output_measured": False,
        "excludes": ["camera_capture", "phone_output_scheduling", "ble_delivery", "motor_response", "audible_speech_onset"],
        "scenarios": [],
    }

    scenario_dirs = sorted(path for path in fixtures_dir.iterdir() if path.is_dir()) if fixtures_dir.exists() else []
    for scenario_dir in scenario_dirs:
        image_path = scenario_dir / "input.jpg"
        if not image_path.exists():
            print(f"[SKIP] {scenario_dir.name}: missing input.jpg")
            continue
        print(f"[BENCHMARK] {scenario_dir.name} ({num_runs} runs)")
        stats = benchmark_scenario(cloud_url, image_path, num_runs=num_runs, timeout=timeout, api_token=api_token)
        report["scenarios"].append(
            {
                "name": scenario_dir.name,
                "image": f"{scenario_dir.name}/input.jpg",
                "latency_ms": stats,
            }
        )
        if stats["successful_runs"]:
            print(f"  P50={stats['p50']:.1f}ms P95={stats['p95']:.1f}ms P99={stats['p99']:.1f}ms success={stats['successful_runs']}/{num_runs}")
        else:
            print(f"  No successful responses; latency unavailable, failures={stats['failed_runs']}")
    return report


def save_benchmark(results: dict[str, Any], output_dir: Path) -> Path:
    """Save a benchmark report as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = str(results.get("git_commit") or "unknown")
    output_path = output_dir / f"latency_benchmark_{timestamp}_{commit}.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark cloud pipeline latency")
    parser.add_argument("--cloud-url", default="http://127.0.0.1:8080")
    parser.add_argument("--fixtures-dir", type=Path, default=Path(__file__).parent.parent / "tests" / "fixtures" / "e2e")
    parser.add_argument("--num-runs", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent.parent / "evaluation" / "latency")
    args = parser.parse_args()
    if args.num_runs < 1 or args.timeout <= 0:
        parser.error("num-runs and timeout must be positive")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if not os.getenv("LIBEREYE_API_TOKEN") and os.getenv("LIBEREYE_ALLOW_INSECURE") != "1":
        parser.error("Configure LIBEREYE_API_TOKEN before benchmarking")

    results = benchmark_cloud_pipeline(args.cloud_url, args.fixtures_dir, args.num_runs, args.timeout)
    output_path = save_benchmark(results, args.output_dir)
    print(f"HTTP measurement report: {output_path}")
    print(f"Scenarios tested: {len(results['scenarios'])}")
    if results["scenarios"]:
        p95_values = [scenario["latency_ms"]["p95"] for scenario in results["scenarios"] if scenario["latency_ms"]["p95"] is not None]
        if p95_values:
            print(f"Mean scenario HTTP P95: {float(np.mean(p95_values)):.1f}ms")
    return 0 if results["scenarios"] and all(scenario["latency_ms"]["failed_runs"] == 0 for scenario in results["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
