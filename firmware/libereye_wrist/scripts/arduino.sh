#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export ARDUINO_DIRECTORIES_DATA="${ARDUINO_DIRECTORIES_DATA:-$firmware_dir/.tools/data}"
export ARDUINO_DIRECTORIES_DOWNLOADS="${ARDUINO_DIRECTORIES_DOWNLOADS:-$firmware_dir/.tools/downloads}"
export ARDUINO_DIRECTORIES_USER="${ARDUINO_DIRECTORIES_USER:-$firmware_dir/.tools/user}"
if [ -n "${ARDUINO_CLI:-}" ]; then
  cli=$ARDUINO_CLI
elif [ -x "$firmware_dir/.tools/arduino-cli" ]; then
  cli=$firmware_dir/.tools/arduino-cli
else
  cli=arduino-cli
fi
exec "$cli" "$@"
