#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${LIBEREYE_BUILD_DIR:-$firmware_dir/build}
if [ "$#" -ne 1 ]; then
  echo 'Usage: ./scripts/flash.sh <USB serial port for the confirmed Feather nRF52840 Express>' >&2
  exit 2
fi
"$firmware_dir/scripts/build.sh"
"$firmware_dir/scripts/arduino.sh" upload --fqbn adafruit:nrf52:feather52840 \
  --port "$1" --input-dir "$build_dir/feather52840" "$firmware_dir"
