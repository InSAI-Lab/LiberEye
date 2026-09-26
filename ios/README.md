# LiberEye iOS relay

This app captures a phone camera image or a frame from licensed HeyCyan glasses, sends it to the LiberEye cloud EPMC controller, and executes authorized wrist and speech actions. The default navigation path does not run a vision model on the phone. Optional direct model and OCR tools are separate utilities and are not an EPMC reproduction path.

## Build and install

Requirements: macOS, Xcode 26.4 or newer, and iOS 26.4 or newer. Run the commands below from this `ios` directory. Both projects use shared schemes and the same `Sources` tree.

| Edition | Project and scheme | Capture source | Dependencies |
| --- | --- | --- | --- |
| Phone and wrist | `LiberEye.xcodeproj`, `LiberEye` | iPhone camera and selected photos | Apple SDKs |
| Licensed glasses | `LiberEyeGlasses.xcodeproj`, `LiberEyeGlasses` | Phone camera and supported glasses | Authorized HeyCyan SDK and vendor license |

### Compile the phone app

```sh
./Scripts/build_app.sh phone build /tmp/libereye-ios
./Scripts/build_app.sh phone simulator /tmp/libereye-simulator
./Scripts/test_contract.sh
```

The first command compiles an unsigned iOS device app. It validates compilation but cannot produce an app installable on an iPhone. The second compiles a Simulator app for local UI inspection. The contract test runs on macOS and does not need device access or vendor frameworks. Open `LiberEye.xcodeproj`, select the `LiberEye` scheme and an installed iOS Simulator to run it. Camera capture, Bluetooth and motor operation require physical devices.

The default app opens without an account. CloudBase login is optional. A cloud URL and token are configured inside Settings when a backend is available. Interface copy, voice commands, and built-in spoken guidance use English. Say "LiberEye" followed by a command such as "Describe the scene" or "Read the text". Offline OCR retains multilingual input recognition.

### Configure signing and create an archive

```sh
mkdir -p .local
cp Configuration/Signing.xcconfig.example .local/Signing.xcconfig
```

Fill in `.local/Signing.xcconfig`:

| Setting | Reader supplies |
| --- | --- |
| `DEVELOPMENT_TEAM` | Apple Developer team ID shown in Xcode |
| `LIBEREYE_BUNDLE_ID` | Registered bundle identifier for the phone app |
| `LIBEREYE_GLASSES_BUNDLE_ID` | Registered bundle identifier for the glasses app |
| `MARKETING_VERSION` | Public app version |
| `CURRENT_PROJECT_VERSION` | Build number, increased for each distributed build |

`org.example.libereye` and `org.example.libereye.glasses` are placeholders. Use identifiers registered to your own team. The editions have distinct identifiers so they can be installed together; their settings and Keychain storage are separate. The local signing file is excluded from the source package. No signing team, certificate or provisioning profile is supplied by this repository.

Open the appropriate Xcode project, add your Apple account in Xcode Settings, choose a connected iPhone and use Run. Xcode handles device provisioning for the configured team. To create a signed Release archive with existing signing assets:

```sh
./Scripts/build_app.sh phone archive /tmp/libereye-archive
```

The script checks that a team and non-placeholder bundle identifier are configured. It does not create accounts, request certificates or upload a build. To export an installable development IPA after a successful signed archive:

```sh
cp Configuration/ExportOptions.plist.example .local/ExportOptions.plist
xcodebuild -exportArchive \
  -archivePath /tmp/libereye-archive/LiberEye.xcarchive \
  -exportOptionsPlist .local/ExportOptions.plist \
  -exportPath /tmp/libereye-ipa
```

The template uses local `debugging` export and the archive's signing team. The target device must be covered by the selected provisioning profile. For TestFlight or another distribution method, use Xcode Organizer and the distribution options available to your Apple Developer account. Never include signing keys or provisioning profiles in a public source archive.

### Build with licensed glasses

1. Obtain the complete authorized iOS SDK from the supplier. Place `QCSDK.framework`, `JLAudioUnitKit.framework` and `JLLogHelper.framework` in `Sources/HeyCyanSDK/SDK/`; place `QCCentralManager.h`, `QCCentralManager.m`, `QCScanViewController.h` and `QCScanViewController.m` in `Sources/HeyCyanSDK/Headers/`; and place the vendor script at `Sources/HeyCyanSDK/Tools/heycyan_license_check.sh`. The app's bridging header and Bluetooth integration require these Objective-C source files as well as the frameworks. The public source package excludes all these dependencies.
2. Copy `Configuration/HeyCyanLicense.env.example` to `.local/HeyCyanLicense.env`, enter your supplier-provided license information and run `chmod 600 .local/HeyCyanLicense.env`. Make the vendor script executable with `chmod +x Sources/HeyCyanSDK/Tools/heycyan_license_check.sh`.
3. Open `LiberEyeGlasses.xcodeproj` and select the `LiberEyeGlasses` scheme and a physical iPhone. The project enables `LIBEREYE_WITH_HEYCYAN`. The vendor frameworks do not support the Simulator.

```sh
./Scripts/build_app.sh glasses build /tmp/libereye-glasses-ios
./Scripts/build_app.sh glasses archive /tmp/libereye-glasses-archive
```

The build phase loads the private license file and runs the original vendor verifier. Its own valid cached license can be used according to the supplier's policy. Missing or expired licensing can stop the build. Do not redistribute vendor dependencies without permission.

## Cloud configuration

Deploy the companion [Python backend](../backend/) on your own server. The [cloud deployment guide](../backend/docs/cloud-deployment.md) describes server requirements, commands and configuration locations. Building the app does not require a running cloud service; cloud analysis requires a reachable deployment.

When deploying, run `python3 scripts/configure_cloud.py` from the server's `backend` directory to generate its private `.env` and API token, then set `LIBEREYE_DOMAIN` to your actual DNS hostname without a scheme or path. The repository's HTTPS configuration reads that value. `libereye.example.org` is a placeholder only and is not an available service.

In app Settings, find **LiberEye Cloud** and fill in:

| App setting | Value |
| --- | --- |
| Enable cloud analysis | Enable when your service is available |
| Server URL | `https://<your-actual-domain>` |
| Access token | The backend's `LIBEREYE_API_TOKEN` |

Select **Save settings**, then **Test service**. The test calls the authenticated `/ready` endpoint and distinguishes a model-ready service from the basic heuristic mode. A successful readiness check does not validate camera capture or actual perception results; analyze a frame to verify those. An authentication failure, unavailable model or unreachable server is shown as an error.

`https://libereye.example.org` illustrates the URL format and must be replaced with your deployed domain. No Swift source change is needed for a domain or token. No production URL, API token, CloudBase environment or model API credential ships in the source defaults.

The cloud token, optional direct model key and CloudBase access/refresh tokens use the iOS Keychain. Older UserDefaults credentials migrate into Keychain on first read. URLs and nonsecret preferences stay in UserDefaults.

Release builds require HTTPS for the cloud API. For an explicitly local Debug experiment, set the Xcode scheme environment variable `LIBEREYE_ALLOW_INSECURE_HTTP=1`; App Transport Security still applies, so use a trusted local TLS endpoint or configure a narrow local-only exception in your own development configuration. Global arbitrary HTTP loading is disabled. The glasses device local network exception remains for vendor media transfer. The relevant platform behavior is documented by Apple in [NSExceptionDomains](https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSAppTransportSecurity/NSExceptionDomains).

CloudBase and direct model access are optional and configured separately in Settings. CloudBase is not the inference service, and a provider secret must not be embedded in an app distributed to other users.

## EPMC contract

`POST /api/mobile/analyze-media` receives a multipart `media` JPEG, optional `target_query`, `detail_request` and `wrist_connected` booleans. Every navigation session uses a new UUID in `X-LiberEye-Session`. The app cancels pending work and discards responses from earlier sessions when the navigation view changes.

Explicit scene description, image questions and image analysis send `detail_request=true`. Automatic glasses captures send `false`. The automatic capture interval is configured in Settings and remains an experimental photo polling loop, not a guarantee of continuous or low latency perception. Model latency, capture time and network delay all add to that interval.

`RelayOutputCoordinator` executes only `output_actions`. `should_speak=false` suppresses speech even if `voice_message` is nonempty. The text in `voice_message` never triggers fallback speech by itself. When no haptic action is present, the app sends STOP so an earlier pattern cannot linger. Cloud errors, leaving monitoring and stopping automatic capture also clear wrist output. A cloud error does not automatically invoke a different model that could bypass EPMC arbitration.

The response decoder accepts the EPMC fields `wrist_cue`, `description_gate`, `description_blocked`, `action_instruction` and `eligible_scene_description`, alongside the compatible mobile response fields. D1 frequency is decoded as a floating-point value of 0.5 Hz.

## Wrist protocol

Use the [wrist firmware and flashing guide](../firmware/libereye_wrist/README.md). The app accepts only the Nordic UART service and the exact control and notification characteristics; an unrelated writable service is not treated as a wrist controller.

| Field | Value |
| --- | --- |
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone writes | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| Phone subscribes | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |
| Command | Exactly three bytes: code, duration high byte, duration low byte |
| Codes | 0 STOP; 1 through 4 D1 through D4; 5 through 7 W1 through W3 |
| Duration | Milliseconds, big endian, bounded to 8000; zero uses firmware defaults |
| Cloud lease | `duration_ms`, normally 3000; cloud `intensity` is not the duration |
| Acknowledgement | `ACK <code> <status>\n` |
| Event | `EVT <code> <status>\n` |

The firmware owns all pulse timing. The phone does not restart patterns with its own repeating timer. W patterns run their complete firmware-defined sequence. A GATT write response confirms BLE transport only. The UI separately waits for the firmware ACK, recognizes busy and rejected commands, and marks feedback unavailable on an ACK timeout or driver failure so subsequent cloud requests can request speech compensation. Reconnect after a timeout or driver failure. The app tracks acknowledgement of the latest requested command; a new STOP or W3 is sent immediately without waiting behind an earlier command. A busy acknowledgement does not queue a lower-priority cue: the next cloud frame resends its current cue. Replacing a pending command does not reset the two-second ACK watchdog. The three-byte protocol has no sequence identifier, so same-code refresh ACKs do not prove delivery of each individual write. There is no pattern deduplication that could leave the wrist silent after a warning completes.

## Device integration

The automated contract test covers explicit speech gating, absence of implicit voice fallback, absent-cue stop selection, fractional D1 frequency, code mapping, big-endian serialization, lease bounds and fragmented firmware acknowledgements. The iOS project additionally needs a device build because the UI and vendor frameworks are not exercised by the standalone contract test.

Camera capture, glasses SDK licensing, end-to-end audio, BLE packet delivery and motor operation require the corresponding services and hardware. Follow the firmware bench procedure and cloud smoke tests before running a supervised hardware evaluation.
