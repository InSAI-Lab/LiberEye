from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libereye.glasses import BleGlassesClient, GlassesMessageProcessor


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive BLE data from camera glasses and run LiberEye agents.")
    parser.add_argument("--address", required=True, help="BLE address or UUID of the glasses.")
    parser.add_argument("--notify-characteristic", required=True, help="BLE notify characteristic UUID.")
    args = parser.parse_args()

    processor = GlassesMessageProcessor()
    client = BleGlassesClient(args.address, args.notify_characteristic)

    def on_message(message) -> None:
        plan = processor.process(message)
        print(asdict(plan))

    asyncio.run(client.run(on_message))


if __name__ == "__main__":
    main()
