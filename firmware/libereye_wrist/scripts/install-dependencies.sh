#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" = Linux ]; then
  nrfutil_env=$firmware_dir/.tools/nrfutil
  python3 -m venv "$nrfutil_env"
  "$nrfutil_env/bin/python" -m pip install 'adafruit-nrfutil==0.5.3.post16'
  "$nrfutil_env/bin/adafruit-nrfutil" version
fi
cli=$firmware_dir/scripts/arduino.sh
index=https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
"$cli" core update-index --additional-urls "$index"
"$cli" core install adafruit:nrf52@1.7.0 --additional-urls "$index"
"$cli" lib install --no-deps 'Adafruit BusIO@1.17.2' 'Adafruit DRV2605 Library@1.2.4'
