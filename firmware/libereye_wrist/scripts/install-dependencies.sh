#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cli=$firmware_dir/scripts/arduino.sh
index=https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
"$cli" core update-index --additional-urls "$index"
"$cli" core install adafruit:nrf52@1.7.0 --additional-urls "$index"
"$cli" lib install --no-deps 'Adafruit BusIO@1.17.2' 'Adafruit DRV2605 Library@1.2.4'
