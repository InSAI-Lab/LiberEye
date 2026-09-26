#!/usr/bin/env sh
set -eu
firmware_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${LIBEREYE_BUILD_DIR:-$firmware_dir/build}
mkdir -p "$build_dir"
"${CXX:-c++}" -std=c++11 -Wall -Wextra -Werror -pedantic \
  "$firmware_dir/tests/haptic_engine_test.cpp" -o "$build_dir/haptic_engine_test"
"$build_dir/haptic_engine_test"
