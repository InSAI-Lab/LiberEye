#!/usr/bin/env python3
"""Download instructions for vision test datasets."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _clone_if_possible(url: str, target_dir: Path) -> bool:
    if target_dir.exists():
        print(f"{target_dir} already exists; skipping clone.")
        return True
    try:
        subprocess.run(["git", "clone", url, str(target_dir)], check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Git clone unavailable or failed: {exc}")
        return False
    print(f"Cloned to {target_dir}")
    return True


def download_guideTWSI(output_dir: Path) -> bool:
    """Print and attempt setup for the GuideTWSI tactile paving dataset."""
    target_dir = output_dir / "guideTWSI"
    print("\nGuideTWSI tactile paving dataset")
    print("URL: https://guidedogrobot-tactile.github.io/")
    print("Repository: https://github.com/GuideTWSI/dataset")
    print("License: review the dataset site before use.")
    print(f"Target images: {target_dir / 'test' / 'images'}")
    print(f"Target labels: {target_dir / 'test' / 'labels'}")
    return _clone_if_possible("https://github.com/GuideTWSI/dataset.git", target_dir)


def download_cdset(output_dir: Path) -> bool:
    """Print and attempt setup for the CDSet-3434 crosswalk dataset."""
    target_dir = output_dir / "cdset"
    print("\nCDSet-3434 crosswalk dataset")
    print("URL: https://github.com/fabvio/CDSet-3434")
    print("License: review the repository before use.")
    print(f"Target test split: {target_dir / 'test'}")
    print("Alternative: Mapillary Vistas crosswalk labels, https://www.mapillary.com/dataset/vistas")
    return _clone_if_possible("https://github.com/fabvio/CDSet-3434.git", target_dir)


def download_lisa(output_dir: Path) -> bool:
    """Print setup instructions for the LISA traffic light dataset."""
    target_dir = output_dir / "lisa"
    print("\nLISA traffic light dataset")
    print("URL: https://www.kaggle.com/datasets/mbornoe/lisa-traffic-light-dataset")
    print("License: review Kaggle terms before use.")
    print("Manual download is required because Kaggle access needs a user account or API token.")
    print(f"Extract the dataset to: {target_dir}")
    print("Alternative: Bosch Small Traffic Lights dataset.")
    return target_dir.exists()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download or print setup instructions for vision test datasets.")
    parser.add_argument("--dataset", choices=["guideTWSI", "cdset", "lisa"], help="Dataset to prepare.")
    parser.add_argument("--all", action="store_true", help="Prepare or print instructions for all datasets.")
    parser.add_argument("--output", type=Path, default=Path("datasets"), help="Output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.dataset and not args.all:
        parser = argparse.ArgumentParser(description="Download or print setup instructions for vision test datasets.")
        parser.add_argument("--dataset", choices=["guideTWSI", "cdset", "lisa"], help="Dataset to prepare.")
        parser.add_argument("--all", action="store_true", help="Prepare or print instructions for all datasets.")
        parser.add_argument("--output", type=Path, default=Path("datasets"), help="Output directory.")
        parser.print_help()
        sys.exit(1)

    args.output.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}
    if args.all or args.dataset == "guideTWSI":
        results["guideTWSI"] = download_guideTWSI(args.output)
    if args.all or args.dataset == "cdset":
        results["cdset"] = download_cdset(args.output)
    if args.all or args.dataset == "lisa":
        results["lisa"] = download_lisa(args.output)

    print("\nSummary")
    for dataset, ok in results.items():
        print(f"- {dataset}: {'ready or cloned' if ok else 'manual setup required'}")
    print("\nNext steps:")
    print("1. Verify each test split is in YOLO format.")
    print("2. Create data.yaml files for each dataset.")
    print("3. Run scripts/evaluate_domain_models.py with the relevant --dataset path.")


if __name__ == "__main__":
    main()
