# LiberEye Wrist Reference Firmware

The LiberEye wristband receives BLE commands from the phone and implements the seven wrist cues in Table 1 of the paper. Its nonblocking scheduler plays both three-pulse groups of W2 and the full long pulse plus four short pulses of W3. It supports priority preemption, explicit stop, disconnect stop, command expiry, and acknowledgements.

The reference hardware is an **Adafruit Feather nRF52840 Express, a DRV2605L carrier with a controllable EN pin, and a 3 V ERM motor**. The FQBN is `adafruit:nrf52:feather52840`. Other controllers, LRA actuators, and custom PCBs require changes to the pin assignments, board package, and driver configuration.

## Wiring and Board Configuration

| Feather pin | DRV2605L pin | Connection |
| :--- | :--- | :--- |
| 3V | VIN | Power for the reference driver board |
| GND | GND | Common ground |
| SDA | SDA | Default board `Wire` pin |
| SCL | SCL | Default board `Wire` pin |
| D5 | EN | Add a 10 kohm pull-down to GND to disable the driver during reset |
| None | OUT+, OUT- | Connect the two ERM motor leads |

The carrier must expose the DRV2605L EN pin, and any conflicting connection that permanently holds EN high must be removed. The standard Adafruit DRV2605L breakout documentation lists power, I2C, and INT pins; do not assume that it exposes an EN header or use INT as EN. A carrier without controllable EN requires a hardware modification or a validated power cutoff circuit to provide the fault shutdown behavior of this reference design. See the [Adafruit pinout guide](https://learn.adafruit.com/adafruit-drv2605-haptic-controller-breakout/pinouts) and [TI datasheet, Section 8.4.1.3](https://www.ti.com/lit/ds/symlink/drv2605l.pdf).

`board_config.h` defines the EN pin, I2C address `0x5A`, fault retry interval, and two-second hardware watchdog. The EN pull-down is part of the fault shutdown path. Permanently holding EN high prevents shutdown during reset. A failed driver I2C write lowers EN, clears playback, and schedules reinitialization attempts every three seconds. Recovery does not replay an old cue. The motor remains idle at startup.

This implementation uses ERM open-loop real-time playback. RTP values are driver commands, not percentage duty cycles, measured acceleration, or carrier frequencies. Use a motor with suitable rated voltage and continuous operation limits. Changing the actuator requires configuration and measurement against the DRV2605L and motor datasheets; replacing `useERM()` with `useLRA()` alone is insufficient.

## Paper Timing and Implementation Defaults

| Pattern | Code | Table 1 command timing | Implementation |
| :--- | :--- | :--- | :--- |
| D1 | 1 | Light, 150 ms every 2000 ms | Period measured from pulse onset |
| D2 | 2 | Light, 150 ms every 1000 ms | Period measured from pulse onset |
| D3 | 3 | Medium, 200 ms every 500 ms | Period measured from pulse onset |
| D4 | 4 | Medium, 200 ms every 250 ms | 200 ms on, 50 ms off |
| W1 | 5 | Two strong 250 ms pulses | Default gap 250 ms; total 750 ms |
| W2 | 6 | Three strong 250 ms pulses, 400 ms pause, then three more | Default gaps within each group 250 ms; total 2900 ms |
| W3 | 7 | One strong 1000 ms pulse, then four strong 150 ms pulses | Default pause after the long pulse 200 ms; short-pulse gaps 150 ms; total 2250 ms |

Default light, medium, and strong RTP commands are 32, 76, and 127. The cloud represents the same ordinal levels with normalized reference intensities of 25, 60, and 100. D1/D2 use the light level, D3/D4 use medium, and W1/W2/W3 use strong. These intensity values are not transmitted in the three-byte BLE protocol. Absolute amplitude, gaps within pulse groups, the pause between the long and short W3 pulses, command leases, preemption, and timeouts are implementation defaults. Calibrate them for the actual motor. Parameters are defined in `haptic_engine.h`.

D patterns repeat until the command lease expires, with a default of 3000 ms and a maximum of 8000 ms. Refreshing the same D pattern extends the lease while preserving pulse phase. W patterns always play one complete sequence and ignore duration. Repeated commands for an active W pattern neither restart nor extend it. A new command after completion starts another sequence.

Priority is W3 > W2 > W1 > D4 > D3 > D2 > D1. A higher-priority command immediately replaces a lower-priority cue; a lower-priority command receives `busy`, and an equal-priority command receives `refresh`. Stop code 0 clears playback at any time. STOP and W3 share a dedicated single-slot queue that ordinary writes cannot fill. Processing an urgent command discards pending ordinary commands, so an old cue cannot resume later. If several urgent writes are pending, the latest one wins. Clients should avoid bursts of unacknowledged commands.

## BLE Protocol

| Field | Value |
| :--- | :--- |
| Advertised name | `LiberEye-Haptic` |
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| RX, phone writes | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| TX, phone subscribes | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

Each GATT write must contain exactly three bytes: `[pattern, duration_hi, duration_lo]`. Duration is an unsigned big-endian value in milliseconds. Zero selects the default; values above 8000 are clamped to 8000. Pattern 0 stops playback, and patterns 1 through 7 map to the table above. STOP is `00 00 00`; D4 for 3000 ms is `04 0B B8`; a complete W3 is `07 00 00`.

Subscribe to TX before sending commands. Write with response is recommended. A successful BLE write confirms transport only; the application must also wait for an ACK. The firmware does not accept JSON, ASCII debug commands, packets split across writes, or multiple commands in one write. It does not retain fragments across writes. Invalid lengths or pattern codes are rejected; writes beyond the characteristic's 20-byte limit are rejected by the BLE stack.

TX sends newline-terminated ASCII messages, each at most 20 bytes:

```text
ACK 7 ok
ACK 7 refresh
ACK 1 busy
ACK 0 stopped
ACK 255 invalid
ACK 7 driver
EVT 7 done
EVT 4 timeout
EVT 0 ready
```

ACK statuses are `ok`, `refresh`, `busy`, `stopped`, `invalid`, `driver`, and `overflow`. An invalid packet length or full ordinary receive queue uses code 255. EVT statuses are `done`, `timeout`, `disconnect`, `driver`, and `ready`. Wireless notifications cannot arrive after disconnection; a connected USB serial port can record `disconnect`. Acknowledgements and events confirm software state and I2C write results, not perceptible motor vibration. A separate FreeRTOS task sends notifications so a blocked TX cannot stall pulse scheduling. A full notification queue may drop status messages, which the phone detects through its ACK timeout.

The phone should explicitly send STOP when monitoring ends, a cloud request becomes invalid, or an action is cancelled. A BLE disconnect event stops playback on the next main-loop iteration. A lost radio link still incurs the supervision timeout before the BLE stack reports disconnection. D leases and finite W sequences bound playback without further commands. The reference firmware permits open BLE access for controlled experiments. Device bonding and authorization are required for deployment outside that setting.

## Installation, Compilation, and Flashing

Use Arduino CLI 1.3.1 with pinned Adafruit nRF52 BSP 1.7.0, Adafruit DRV2605 Library 1.2.4, and Adafruit BusIO 1.17.2. The BSP supplies Bluefruit. `sketch.yaml` also records the reference build profile.

Install the CLI using the [Arduino installation guide](https://arduino.github.io/arduino-cli/1.3/installation/), then run from this directory:

```sh
./scripts/install-dependencies.sh
./scripts/build.sh
```

The toolchain and libraries default to `.tools` in this directory; build output defaults to `build/feather52840`. Both are ignored. Place the CLI at `.tools/arduino-cli`, or set `ARDUINO_CLI` to an existing executable. Set `ARDUINO_DIRECTORIES_DATA`, `ARDUINO_DIRECTORIES_DOWNLOADS`, and `ARDUINO_DIRECTORIES_USER` to use external caches. Set `LIBEREYE_BUILD_DIR` to change the output directory for host tests and firmware builds.

Flash only after confirming that the connected device is the reference board specified above:

```sh
./scripts/arduino.sh board list
./scripts/flash.sh /dev/cu.usbmodemYOUR_BOARD
```

Replace the serial path with the actual port, commonly `/dev/ttyACM0` on Linux or `COM3` on Windows. The script reruns tests and compilation before flashing through the board's serial DFU bootloader. Do not upload the Feather build to a different nRF52840 board. A blank chip on a custom PCB requires a board-specific bootloader, SoftDevice, flash memory layout and SWD workflow. See the [Adafruit board and bootloader guide](https://learn.adafruit.com/introducing-the-adafruit-nrf52840-feather/arduino-bsp-setup) and [Adafruit driver library guide](https://learn.adafruit.com/adafruit-drv2605-haptic-controller-breakout/arduino-code).

## Tests

Run host timing tests without hardware:

```sh
./scripts/test.sh
```

The tests check pulse onsets and boundaries at each millisecond for all seven patterns, complete W1/W2/W3 sequences, W3 preemption, rejection of lower-priority commands, refresh without restart, immediate stop, default and maximum D leases, 32-bit clock rollover, and strict packet lengths.

For hardware validation, inspect I2C RTP writes with a logic analyzer or measure vibration with an accelerometer. Check all seven patterns, W3 during D1, STOP during W3, disconnection, EN shutdown after an SDA fault, and watchdog reset after a main-loop stall. Record the firmware version, BSP, board, driver, actuator, vibration amplitude, and response latency.
