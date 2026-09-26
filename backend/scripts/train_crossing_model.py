from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO crosswalk or traffic-light model for LiberEye.")
    parser.add_argument("--data", required=True, help="Path to YOLO dataset YAML.")
    parser.add_argument("--model", default="yolo26n.pt", help="Base YOLO model, for example yolo26n.pt or yolo26n-seg.pt.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--project", default="runs/crossing")
    parser.add_argument("--name", default="crossing_yolo")
    parser.add_argument("--device", default=None, help="Optional device, for example cpu, 0, or mps.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset YAML not found: {data_path}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("ultralytics is required. Install it in the libereye env first.") from exc

    model = YOLO(args.model)
    train_args = {
        "data": str(data_path),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "project": args.project,
        "name": args.name,
    }
    if args.device:
        train_args["device"] = args.device
    result = model.train(**train_args)

    best = Path(args.project) / args.name / "weights" / "best.pt"
    print("\nTraining finished.")
    print(f"Ultralytics result: {result}")
    print(f"Best weights: {best}")
    print("\nUse as crosswalk model:")
    print(f"LIBEREYE_ENABLE_STRONG_VISION=1 LIBEREYE_CROSSWALK_MODEL={best} python -m libereye.server --port 8012")
    print("\nUse as traffic-light model:")
    print(f"LIBEREYE_ENABLE_STRONG_VISION=1 LIBEREYE_TRAFFIC_LIGHT_MODEL={best} python -m libereye.server --port 8012")


if __name__ == "__main__":
    main()
