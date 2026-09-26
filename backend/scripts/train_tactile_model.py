from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO tactile paving detector for LiberEye.")
    parser.add_argument("--data", required=True, help="Path to YOLO dataset YAML exported from Roboflow or Label Studio.")
    parser.add_argument("--model", default="yolo26n.pt", help="Base YOLO detection model, for example yolo26n.pt or yolo11n.pt.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--project", default="runs/tactile")
    parser.add_argument("--name", default="tactile_yolo")
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

    run_dir = Path(args.project) / args.name
    best = run_dir / "weights" / "best.pt"
    print("\nTraining finished.")
    print(f"Ultralytics result: {result}")
    print(f"Best weights: {best}")
    print("\nUse this model with LiberEye:")
    print(f"LIBEREYE_ENABLE_STRONG_VISION=1 LIBEREYE_TACTILE_MODEL={best} python -m libereye.server --port 8012")


if __name__ == "__main__":
    main()
