# Algorithm and implementation

LiberEye converts perception updates into mobility events, selects a wrist cue, and gates optional speech through Event Priority Multimodal Coordination (EPMC).

| Paper element or component | Implementation |
| --- | --- |
| Eq. (1), mobility event representation | [models.py](../backend/libereye/models.py), [mobility_events.py](../backend/libereye/mobility_events.py) |
| Perception modules | [perception_modules.py](../backend/libereye/perception_modules.py) |
| Algorithm 1, wrist selection and speech admission | [epmc.py](../backend/libereye/epmc.py), `EPMCCoordinator.coordinate()` |
| Eq. (2), cue priority | [wrist_haptics.py](../backend/libereye/wrist_haptics.py), [mobility_events.py](../backend/libereye/mobility_events.py) |
| Eq. (3), description gate | [epmc.py](../backend/libereye/epmc.py) |
| Supervisory stop override | [supervisory_module.py](../backend/libereye/supervisory_module.py) |
| Scene persistence | [scene_persistence.py](../backend/libereye/scene_persistence.py) |
| Context planning and specialist coordination | [context_planner.py](../backend/libereye/context_planner.py), [specialists.py](../backend/libereye/specialists.py), [mobility_coordinator.py](../backend/libereye/mobility_coordinator.py) |
| Phone relay | [smartphone_relay.py](../backend/libereye/smartphone_relay.py), [cloud_api.py](../backend/libereye/cloud_api.py), [LiberEyeCloudService.swift](../ios/Sources/Services/LiberEyeCloudService.swift) |
| Table 1, wrist timing | [wrist_haptics.py](../backend/libereye/wrist_haptics.py), [haptic_engine.h](../firmware/libereye_wrist/haptic_engine.h) |
| BLE and motor control | [BluetoothManager.swift](../ios/Sources/Managers/BluetoothManager.swift), [libereye_wrist.ino](../firmware/libereye_wrist/libereye_wrist.ino) |

## Event coordination

Each mobility event contains its source module, severity, confidence, eligible modalities, and recommendation, following Eq. (1). Events may also supply a candidate wrist cue or identify optional scene detail. Module confidence gates filter wrist candidates and spoken recommendations. The fused severity is the highest event or supervisory severity.

Algorithm 1 takes candidate cues `H_t`, supervisory override `o_t`, fused severity `s_t`, context change `Delta_t`, and detail request `q_t`:

1. If `o_t` is true, select W3 and preserve the supervisory stop instruction.
2. Otherwise, select the highest priority candidate under Eq. (2): `W3 > W2 > W1 > D4 > D3 > D2 > D1`.
3. Compute the blocking condition `u_t = (h_t in {W1, W2, W3, D4}) or (s_t == danger)`.
4. Apply Eq. (3): `g_t = not u_t and (Delta_t or q_t)`.
5. Append eligible optional descriptions only when `g_t` is true. Concise action guidance remains eligible.

A detail request cannot override urgent speech suppression. An empty candidate set produces no wrist cue and retains any eligible voice action. When several events match a cue, action selection uses descending severity, descending confidence, then stable input order.

The scene state machine tracks sidewalk, approaching crossing, crossing, and recovery. A transition requires three consecutive observations; the first update establishes changed context. Explicit detail requests, finding or chat intent, and a target query set `q_t`.

## Wrist cues

Table 1 specifies the following command timing. Pulse periods are measured from the start of one pulse to the start of the next.

| Cue | Meaning | Intensity | Pulse timing |
| --- | --- | --- | --- |
| D1 | Nominal distance 3 to 5 m | Light | 150 ms every 2000 ms |
| D2 | Nominal distance 1.5 to 3 m | Light | 150 ms every 1000 ms |
| D3 | Nominal distance 0.8 to 1.5 m | Medium | 200 ms every 500 ms |
| D4 | Distance below 0.8 m | Medium | 200 ms every 250 ms |
| W1 | Attention | Strong | Two 250 ms pulses |
| W2 | Avoidance | Strong | Three 250 ms pulses, a 400 ms pause, then three 250 ms pulses |
| W3 | Stop | Strong | One 1000 ms pulse, then four 150 ms pulses |

The implementation assigns the 1.5 m and 3 m boundaries to the nearer distance band. Invalid or missing distance values produce no proximity cue.

Engineering defaults supply values not specified by the timing table:

| Parameter | Default |
| --- | --- |
| Confidence gates for obstacle/tactile, traffic/crossing, search/scene/text modules | 0.55, 0.65, 0.50 |
| W1 and W2 gaps within each pulse group | 250 ms |
| Gap after the initial W3 pulse | 200 ms |
| Gaps between W3 short pulses | 150 ms |
| Light, medium, strong API intensity values | 25, 60, 100 |
| Light, medium, strong signed RTP commands | 32, 76, 127 |
| D cue lease | 3000 ms by default, capped at 8000 ms |

These settings give total W1, W2, and W3 durations of 750 ms, 2900 ms, and 2250 ms. Intensity values are ordinal reference commands and require calibration for the actuator. They do not represent measured acceleration or perceived intensity.

The [reference firmware](../firmware/libereye_wrist/README.md) accepts one three byte BLE command per write: `[pattern, duration_hi, duration_lo]`. Pattern codes 1 through 7 select D1 through W3; code 0 stops output. Duration is in milliseconds with big endian encoding. D cues repeat until their lease expires; a matching refresh renews the lease without restarting pulse phase. W cues play a complete finite sequence regardless of duration, and matching refreshes do not restart or extend it. Higher priority cues preempt lower priority cues. STOP clears playback immediately, and BLE disconnection clears playback when detected by the stack.

## Software validation

From the repository root:

```sh
python3 scripts/validate_epmc.py
./firmware/libereye_wrist/scripts/test.sh
```

[validate_epmc.py](../scripts/validate_epmc.py) checks all 3072 combinations of candidate subsets, override, severity, context change, and detail request. It also replays synthetic scenarios under the S, AH, and AHC software policies. [Backend tests](../backend/tests/) cover event handling, relay behavior, and API integration. Firmware tests cover pulse boundaries, sequence completion, priority, refresh, STOP, leases, clock rollover, and packet decoding.

Replay counters count generated plans, and reported processing times cover coordinator execution. Measure network transport, speech onset, BLE transfer, motor response and perceived intensity separately on the assembled system. Model inference tests use the configured model weights and runtime dependencies; synthetic fixtures exercise the coordination policy.
