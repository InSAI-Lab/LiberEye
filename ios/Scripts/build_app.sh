#!/bin/bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: build_app.sh [phone|glasses] [build|simulator|archive] [output-directory]

  build      Compile an unsigned Debug app for iOS device build validation.
  simulator  Compile an unsigned Debug app for the iOS Simulator (phone only).
  archive    Create a signed Release archive using your local signing settings.

The default is phone build. Output defaults to the system temporary directory.
Configure .local/Signing.xcconfig before archive or installation on a device.
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if [[ $# -gt 3 ]]; then
    usage >&2
    exit 2
fi

variant="${1:-phone}"
action="${2:-build}"
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$variant" in
    phone) scheme="LiberEye" ;;
    glasses) scheme="LiberEyeGlasses" ;;
    *) usage >&2; exit 2 ;;
esac
case "$action" in
    build|archive) destination="generic/platform=iOS" ;;
    simulator)
        if [[ "$variant" != "phone" ]]; then
            echo "The licensed glasses SDK supports physical iOS devices only." >&2
            exit 2
        fi
        destination="generic/platform=iOS Simulator"
        ;;
    *) usage >&2; exit 2 ;;
esac

if [[ "$variant" == "glasses" ]]; then
    for dependency in \
        SDK/QCSDK.framework \
        SDK/JLAudioUnitKit.framework \
        SDK/JLLogHelper.framework \
        Headers/QCCentralManager.h \
        Headers/QCCentralManager.m \
        Headers/QCScanViewController.h \
        Headers/QCScanViewController.m \
        Tools/heycyan_license_check.sh; do
        if [[ ! -e "$project_dir/Sources/HeyCyanSDK/$dependency" ]]; then
            echo "Missing licensed glasses dependency: Sources/HeyCyanSDK/$dependency" >&2
            echo "Use the phone build or install the authorized SDK as described in README.md." >&2
            exit 1
        fi
    done
fi

output_dir="${3:-${TMPDIR:-/tmp}/libereye-build/$scheme}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
build_args=(
    -project "$project_dir/$scheme.xcodeproj"
    -scheme "$scheme"
    -destination "$destination"
    -derivedDataPath "$output_dir/DerivedData"
    -hideShellScriptEnvironment
)

if [[ "$action" == "archive" ]]; then
    settings="$(xcodebuild "${build_args[@]}" -configuration Release -showBuildSettings)"
    team="$(printf '%s\n' "$settings" | sed -n 's/^ *DEVELOPMENT_TEAM = *//p' | head -n 1)"
    bundle_id="$(printf '%s\n' "$settings" | sed -n 's/^ *PRODUCT_BUNDLE_IDENTIFIER = *//p' | head -n 1)"
    if [[ -z "$team" || -z "$bundle_id" || "$bundle_id" == org.example.* ]]; then
        echo "Set DEVELOPMENT_TEAM and your registered bundle identifier in .local/Signing.xcconfig." >&2
        exit 1
    fi
    xcodebuild "${build_args[@]}" -configuration Release \
        -archivePath "$output_dir/$scheme.xcarchive" archive
    echo "Signed archive: $output_dir/$scheme.xcarchive"
else
    xcodebuild "${build_args[@]}" -configuration Debug CODE_SIGNING_ALLOWED=NO build
    if [[ "$action" == "simulator" ]]; then
        echo "Simulator app: $output_dir/DerivedData/Build/Products/Debug-iphonesimulator/$scheme.app"
    else
        echo "Unsigned validation app: $output_dir/DerivedData/Build/Products/Debug-iphoneos/$scheme.app"
        echo "Use a signed archive or Xcode Run to install on an iPhone."
    fi
fi
