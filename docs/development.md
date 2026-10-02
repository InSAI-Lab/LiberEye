# Development

## Run CI on the latest code

Open [Source validation in GitHub Actions](https://github.com/InSAI-Lab/LiberEye/actions/workflows/ci.yml), click **Run workflow**, select **main**, and click **Run workflow** again. This creates a new run for the latest commit on `main` at the time it is triggered. Pushes and pull requests also trigger validation automatically.

To start the same check from GitHub CLI:

```bash
gh workflow run ci.yml --repo InSAI-Lab/LiberEye --ref main
```

**Re-run jobs** repeats the original run's commit. To check newer code, start a new run with **Run workflow**.

## Python backend

Use Python 3.11 or 3.12 and install the development dependencies from [the backend](../backend/):

```bash
cd backend
python -m pip install -c constraints.txt '.[dev,hardware]'
python -m pytest tests
python ../scripts/validate_epmc.py
python -m build
```

The tests exercise event fusion, priority selection, speech admission, session isolation, authentication, media validation and relay contracts. Optional real-model tests require the model weights and input images described in [the vision fixtures guide](../backend/tests/fixtures/vision/README.md). The algorithm validator exhausts candidate-cue subsets, supervisory override, severity, context changes and detail requests, then runs synthetic frame replay.

To run the local HTTP smoke check, start a configured backend as described in the [deployment guide](../backend/docs/cloud-deployment.md), then run `python scripts/smoke_cloud.py` from `backend/`. It reads the local `.env` for authentication. Use disposable session identifiers for smoke tests.

## iOS

On macOS with Xcode 26.4 or newer:

```bash
./ios/Scripts/test_contract.sh
xcodebuild -project ios/LiberEye.xcodeproj -scheme LiberEye \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/libereye-ios CODE_SIGNING_ALLOWED=NO build
```

The Swift contract tests cover response parsing, explicit speech admission, stop selection, command encoding and firmware acknowledgements. The app build checks UI and system framework integration. The optional glasses project requires vendor dependencies documented in the [iOS guide](../ios/README.md).

## Wrist firmware

Host tests require a C++11 compiler. Board compilation additionally requires Arduino CLI and the specified Adafruit dependencies:

```bash
./firmware/libereye_wrist/scripts/test.sh
./firmware/libereye_wrist/scripts/install-dependencies.sh
LIBEREYE_BUILD_DIR=/tmp/libereye-firmware \
  ./firmware/libereye_wrist/scripts/build.sh
```

See the [firmware guide](../firmware/libereye_wrist/README.md) for the reference wiring and upload command. Automated timing tests exercise the pulse scheduler and command handling. Use the assembled hardware to measure actuator onset, BLE delivery and perceived intensity.

## Source archive

From the project root:

```bash
python -m unittest discover -s tests
python scripts/package_source.py
```

The archive contains source, tests, configuration templates and documentation. Packaging tests check exclusion rules, symbolic links, file checksums and reproducibility. Keep local secrets in the ignored configuration locations and install optional vendor dependencies privately.
