#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${LIBEREYE_BUILD_DIR:-$firmware_dir/build}
"$firmware_dir/scripts/test.sh"
"$firmware_dir/scripts/arduino.sh" compile --fqbn adafruit:nrf52:feather52840 \
  --warnings all --output-dir "$build_dir/feather52840" "$firmware_dir"
