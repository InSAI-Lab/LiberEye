#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT HUP INT TERM
xcrun swiftc \
  "$PROJECT_ROOT/Sources/Models/CloudConnectionConfiguration.swift" \
  "$PROJECT_ROOT/Sources/Models/WristProtocol.swift" \
  "$PROJECT_ROOT/Sources/Models/LiberEyeCloudPlan.swift" \
  "$PROJECT_ROOT/Tests/RelayContractTests.swift" \
  -o "$TEST_DIR/relay-contract-tests"
"$TEST_DIR/relay-contract-tests"
