#!/usr/bin/env python3
"""Baseline evaluation for domain-specific vision models."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


def _metric_value(metrics: Any, family: str, name: str) -> float | None:
    family_metrics = getattr(metrics, family, None)
    if family_metrics is None:
        return None
    value = getattr(family_metrics, name, None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_model(model_path: str) -> Any:
    if YOLO is None:
        raise SystemExit("ultralytics is required. Install with: pip install ultralytics>=8.3.237")
    return YOLO(model_path)


def evaluate_tactile(model_path: str, dataset_yaml: str) -> dict[str, Any]:
    """Evaluate a tactile paving segmentation model."""
    model = _load_model(model_path)
    metrics = model.val(data=dataset_yaml, split="test", verbose=False)
    return {
        "domain": "tactile_paving",
        "model": model_path,
        "dataset": dataset_yaml,
        "mIoU": _metric_value(metrics, "seg", "map"),
        "mAP@0.5": _metric_value(metrics, "box", "map50"),
        "precision": _metric_value(metrics, "box", "p"),
        "recall": _metric_value(metrics, "box", "r"),
        "boundary_f1": None,
        "boundary_f1_note": (
            "Requires ground-truth segmentation masks and boundary extraction "
            "before pixel-tolerance F1 can be computed."
        ),
    }


def evaluate_crosswalk(model_path: str, dataset_yaml: str) -> dict[str, Any]:
    """Evaluate a crosswalk detection or segmentation model."""
    model = _load_model(model_path)
    metrics = model.val(data=dataset_yaml, split="test", verbose=False)
    recall = _metric_value(metrics, "box", "r")
    return {
        "domain": "crosswalk",
        "model": model_path,
        "dataset": dataset_yaml,
        "mAP@0.5": _metric_value(metrics, "box", "map50"),
        "precision": _metric_value(metrics, "box", "p"),
        "recall": recall,
        "miss_rate": None if recall is None else 1.0 - recall,
    }


def evaluate_traffic_light(model_path: str, dataset_yaml: str) -> dict[str, Any]:
    """Evaluate a traffic light state detection model."""
    model = _load_model(model_path)
    metrics = model.val(data=dataset_yaml, split="test", verbose=False)
    return {
        "domain": "traffic_light",
        "model": model_path,
        "dataset": dataset_yaml,
        "mAP@0.5": _metric_value(metrics, "box", "map50"),
        "precision": _metric_value(metrics, "box", "p"),
        "recall": _metric_value(metrics, "box", "r"),
        "state_switch_latency_frames": None,
        "state_switch_latency_note": (
            "Requires video clips with annotated light-state transition timestamps "
            "before frame-level latency can be measured."
        ),
    }


def save_baseline(results: dict[str, Any], output_dir: Path) -> Path:
    """Save baseline results to a timestamped JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
        ).strip()
    except Exception:
        commit_hash = "unknown"

    timestamp = datetime.now()
    results["timestamp"] = timestamp.isoformat()
    results["commit_hash"] = commit_hash
    output_path = output_dir / f"baseline_yolo26n_{timestamp:%Y%m%d}_{commit_hash}.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Baseline saved to: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate domain vision models.")
    parser.add_argument("--baseline", action="store_true", help="Show generic YOLO26n baseline setup guidance.")
    parser.add_argument("--tactile", help="Tactile paving model path.")
    parser.add_argument("--crosswalk", help="Crosswalk model path.")
    parser.add_argument("--traffic-light", help="Traffic light model path.")
    parser.add_argument("--dataset", help="YOLO dataset YAML path.")
    parser.add_argument("--output-dir", default="evaluation/baselines", help="Directory for JSON baseline results.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.baseline:
        print("Generic YOLO26n baseline evaluation requires prepared YOLO-format test datasets.")
        print("Use scripts/download_vision_testsets.py to collect datasets, then pass --dataset with each model flag.")
        return

    if not args.dataset:
        raise SystemExit("--dataset is required when evaluating a model.")

    output_dir = Path(args.output_dir)
    if args.tactile:
        save_baseline(evaluate_tactile(args.tactile, args.dataset), output_dir)
    if args.crosswalk:
        save_baseline(evaluate_crosswalk(args.crosswalk, args.dataset), output_dir)
    if args.traffic_light:
        save_baseline(evaluate_traffic_light(args.traffic_light, args.dataset), output_dir)
    if not any((args.tactile, args.crosswalk, args.traffic_light)):
        raise SystemExit("Specify --baseline or at least one model flag.")


if __name__ == "__main__":
    main()
