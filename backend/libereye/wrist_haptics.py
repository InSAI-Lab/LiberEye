from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Literal, Protocol

from .models import HapticCue, HapticPattern, Severity

IntensityLevel = Literal["Light", "Medium", "Strong"]
# Normalized API values round to the signed RTP magnitudes in haptic_engine.h.
# Neither representation is a calibrated acceleration or duty cycle.
REFERENCE_RTP_MAGNITUDES: Dict[IntensityLevel, int] = {"Light": 32, "Medium": 76, "Strong": 127}


@dataclass(frozen=True)
class WristCueProfile:
    """Paper timing plus explicit engineering defaults for undocumented values."""
    pattern: HapticPattern
    meaning: str
    intensity: IntensityLevel
    intensity_value: int  # Normalized reference strength, not measured amplitude
    width_s: float
    timing: str
    frequency_hz: float
    risk_level: Severity
    description: str


# Numeric intensities and intra-group gaps are engineering defaults.
# W2 pulse width follows Table 1 of the paper.
# Firmware pattern selection controls timing and motor amplitude. W frequency
# is zero to denote a finite sequence, not a periodic pulse onset rate.
TABLE1_WRIST_CUES: Dict[HapticPattern, WristCueProfile] = {
    "D1": WristCueProfile(
        pattern="D1",
        meaning="3 to 5 m",
        intensity="Light",
        intensity_value=25,
        width_s=0.15,
        timing="0.5 Hz",
        frequency_hz=0.5,
        risk_level="info",
        description="Distant approach: light 0.15-second pulse every 2 seconds (3-5 m)",
    ),
    "D2": WristCueProfile(
        pattern="D2",
        meaning="1.5 to 3 m",
        intensity="Light",
        intensity_value=25,
        width_s=0.15,
        timing="1 Hz",
        frequency_hz=1,
        risk_level="warn",
        description="Medium-distance approach: light 0.15-second pulse every second (1.5-3 m)",
    ),
    "D3": WristCueProfile(
        pattern="D3",
        meaning="0.8 to 1.5 m",
        intensity="Medium",
        intensity_value=60,
        width_s=0.20,
        timing="2 Hz",
        frequency_hz=2,
        risk_level="warn",
        description="Close: medium-strength 0.2-second pulse every 0.5 seconds (0.8-1.5 m)",
    ),
    "D4": WristCueProfile(
        pattern="D4",
        meaning="Below 0.8 m",
        intensity="Medium",
        intensity_value=60,
        width_s=0.20,
        timing="4 Hz",
        frequency_hz=4,
        risk_level="warn",
        description="Very close: medium-strength 0.2-second pulse every 0.25 seconds (within 0.8 m)",
    ),
    "W1": WristCueProfile(
        pattern="W1",
        meaning="Attention",
        intensity="Strong",
        intensity_value=100,
        width_s=0.25,
        timing="2 pulses",
        frequency_hz=0,
        risk_level="warn",
        description="Hazard warning: two strong 0.25-second pulses",
    ),
    "W2": WristCueProfile(
        pattern="W2",
        meaning="Avoidance",
        intensity="Strong",
        intensity_value=100,
        width_s=0.25,
        timing="3 + 3 pulses, 0.4 s gap",
        frequency_hz=0,
        risk_level="warn",
        description="Immediate avoidance: three strong short pulses, a 0.4-second pause, then three strong short pulses",
    ),
    "W3": WristCueProfile(
        pattern="W3",
        meaning="Stop",
        intensity="Strong",
        intensity_value=100,
        width_s=1.0,
        timing="1 + 4 x 0.15",
        frequency_hz=0,
        risk_level="danger",
        description="Emergency stop: one strong 1-second pulse followed by four rapid short pulses",
    ),
}

# Equation (2): Priority ordering: W3 > W2 > W1 > D4 > D3 > D2 > D1
WRIST_CUE_PRIORITY_ORDER: List[HapticPattern] = ["W3", "W2", "W1", "D4", "D3", "D2", "D1"]
WRIST_CUE_PRIORITY_RANK: Dict[HapticPattern, int] = {
    "W3": 7,
    "W2": 6,
    "W1": 5,
    "D4": 4,
    "D3": 3,
    "D2": 2,
    "D1": 1,
}

WRIST_PROTOCOL = "libereye-wrist-v1"
WRIST_STATUS_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
WRIST_PATTERN_CODES = {pattern: index for index, pattern in enumerate(("D1", "D2", "D3", "D4", "W1", "W2", "W3"), 1)}


def encode_wrist_command(pattern: HapticPattern | None, duration_ms: int = 3000) -> bytes:
    """Encode one GATT write: pattern byte, big-endian duration in ms.

    None stops output. D patterns repeat for duration_ms (zero uses firmware
    default). W patterns finish their complete sequence regardless of duration.
    Intensity is an ordinal firmware setting, not a byte in this protocol.
    """
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 0 <= duration_ms <= 8000:
        raise ValueError("duration_ms must be an integer from 0 to 8000")
    if pattern is None:
        return bytes((0, 0, 0))
    get_wrist_cue_profile(pattern)
    return bytes((WRIST_PATTERN_CODES[pattern], duration_ms >> 8, duration_ms & 0xff))


def wrist_timing_profile(pattern: HapticPattern) -> Dict[str, Any]:
    """Explicit commanded timing; never a claim of measured actuator response."""
    profile = get_wrist_cue_profile(pattern)
    if pattern.startswith("D"):
        pulses = [round(profile.width_s * 1000)]
        gaps = [round(1000 / profile.frequency_hz) - pulses[0]]
    elif pattern == "W1":
        pulses, gaps = [250, 250], [250]
    elif pattern == "W2":
        pulses, gaps = [250] * 6, [250, 250, 400, 250, 250]
    else:
        pulses, gaps = [1000, 150, 150, 150, 150], [200, 150, 150, 150]
    return {
        "pulse_widths_ms": pulses,
        "gaps_ms": gaps,
        "repeat": pattern.startswith("D"),
        "intensity_label": profile.intensity,
        "reference_intensity": profile.intensity_value,
        "reference_rtp": REFERENCE_RTP_MAGNITUDES[profile.intensity],
        "amplitude_calibrated": False,
        "engineering_defaults": ["motor_amplitude"] + (["intra_group_gaps"] if pattern.startswith("W") else []),
    }


def get_wrist_cue_profile(pattern: HapticPattern) -> WristCueProfile:
    """Retrieve Table 1 profile for a wrist cue."""
    if pattern not in TABLE1_WRIST_CUES:
        raise ValueError(f"Unknown wrist cue pattern: {pattern}. Supported: {list(TABLE1_WRIST_CUES)}")
    return TABLE1_WRIST_CUES[pattern]


def create_haptic_cue(pattern: HapticPattern) -> HapticCue:
    """Create a HapticCue object initialized from Table 1 specifications."""
    profile = get_wrist_cue_profile(pattern)
    return HapticCue(
        device="bracelet",
        pattern=profile.pattern,
        frequency_hz=profile.frequency_hz,
        intensity=profile.intensity_value,
        risk_level=profile.risk_level,
        meaning=profile.description,
    )


class WristCueDriver(Protocol):
    """Protocol for sending wrist haptic cues."""
    def send(self, cue: HapticCue) -> None:
        raise NotImplementedError


class MockWristDriver:
    """Development driver that logs wrist commands without physical hardware."""
    def __init__(self) -> None:
        self.last_sent: HapticCue | None = None

    def send(self, cue: HapticCue) -> None:
        self.last_sent = cue
        print("[wrist-cue]", json.dumps(asdict(cue), ensure_ascii=False))


class SerialWristDriver:
    """Legacy JSON serial adapter, separate from the BLE release protocol."""
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for SerialWristDriver") from exc
        self._serial = serial.Serial(port, baudrate=baudrate, timeout=1)

    def send(self, cue: HapticCue) -> None:
        payload = {
            "pattern": cue.pattern,
            "frequency_hz": cue.frequency_hz,
            "intensity": cue.intensity,
            "risk_level": cue.risk_level,
            "meaning": cue.meaning,
        }
        self._serial.write((json.dumps(payload) + "\n").encode("utf-8"))


class BleWristDriver:
    """Synchronous bench driver that keeps BLE connected through cue completion.

    Mobile deployments use the phone's persistent BLE session instead. A write
    alone is not completion: the firmware stops immediately on disconnect.
    """
    def __init__(self, address: str, characteristic_uuid: str) -> None:
        self.address = address
        self.characteristic_uuid = characteristic_uuid

    def send(self, cue: HapticCue) -> None:
        asyncio.run(self._send_async(cue))

    async def _send_async(self, cue: HapticCue) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("bleak is required for BleWristDriver") from exc

        statuses: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        buffer = bytearray()
        code = WRIST_PATTERN_CODES[cue.pattern]

        def receive_status(_sender: Any, data: bytearray) -> None:
            buffer.extend(data)
            if len(buffer) > 256:
                buffer.clear()
                return
            while b"\n" in buffer:
                line, _, remaining = buffer.partition(b"\n")
                buffer[:] = remaining
                try:
                    kind, raw_code, outcome = line.decode("ascii").strip().split()
                    status_code = int(raw_code)
                except (UnicodeError, ValueError):
                    continue
                if kind in {"ACK", "EVT", "EVENT"}:
                    loop.call_soon_threadsafe(statuses.put_nowait, (kind, status_code, outcome))

        def disconnected(_client: Any) -> None:
            loop.call_soon_threadsafe(statuses.put_nowait, ("EVT", 255, "disconnect"))

        async def await_status(kind: str, outcomes: set[str], timeout: float) -> None:
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(f"Wristband did not confirm {kind} for {cue.pattern}")
                status_kind, status_code, outcome = await asyncio.wait_for(statuses.get(), remaining)
                if outcome in {"driver", "disconnect"}:
                    raise ConnectionError(f"Wristband reported {outcome}")
                if status_kind == "ACK" and status_code in {code, 255} and outcome not in {"ok", "refresh"}:
                    raise RuntimeError(f"Wristband rejected {cue.pattern}: {outcome}")
                if status_code == code and (status_kind == kind or (kind == "EVT" and status_kind == "EVENT")):
                    if outcome in outcomes:
                        return

        async with BleakClient(self.address, disconnected_callback=disconnected) as client:
            await client.start_notify(WRIST_STATUS_UUID, receive_status)
            await client.write_gatt_char(self.characteristic_uuid, encode_wrist_command(cue.pattern), response=True)
            await await_status("ACK", {"ok", "refresh"}, 2.0)
            profile = wrist_timing_profile(cue.pattern)
            duration_ms = 3000 if profile["repeat"] else sum(profile["pulse_widths_ms"]) + sum(profile["gaps_ms"])
            await await_status("EVT", {"timeout" if profile["repeat"] else "done"}, duration_ms / 1000 + 2.0)


class FallbackWristDriver:
    """Wraps another wrist driver and implements fallback voice compensation on disconnect (Section 2.3).

    'Available speech can convey wrist warnings. Reverse substitution is limited
    to the tactile vocabulary.'
    """
    def __init__(self, driver: WristCueDriver) -> None:
        self._driver = driver
        self.pending_voice_messages: list[str] = []
        self.connected: bool = True

    def send(self, cue: HapticCue) -> None:
        try:
            self._driver.send(cue)
            self.connected = True
        except Exception:
            self.connected = False
            # Fallback to speech for wrist warnings
            profile = TABLE1_WRIST_CUES.get(cue.pattern)
            desc = profile.description if profile else cue.meaning
            voice_desc = f"[Wrist disconnected speech fallback] Haptic warning {cue.pattern}: {desc}"
            self.pending_voice_messages.append(voice_desc)
            print(f"[wrist-fallback] {voice_desc}")

    def pop_voice_messages(self) -> list[str]:
        msgs = list(self.pending_voice_messages)
        self.pending_voice_messages.clear()
        return msgs


def create_wrist_driver(transport: str | None = None) -> WristCueDriver:
    """Factory creating wrist haptic driver based on LIBEREYE_BRACELET_TRANSPORT."""
    t = (transport or os.getenv("LIBEREYE_BRACELET_TRANSPORT", "mock")).lower()
    if t == "mock":
        return MockWristDriver()
    if t == "serial":
        port = os.getenv("LIBEREYE_BRACELET_PORT", "/dev/ttyUSB0")
        baudrate = int(os.getenv("LIBEREYE_BRACELET_BAUDRATE", "115200"))
        return SerialWristDriver(port=port, baudrate=baudrate)
    if t == "ble":
        address = os.getenv("LIBEREYE_BRACELET_ADDRESS", "")
        uuid = os.getenv("LIBEREYE_BRACELET_UUID", "")
        if not address or not uuid:
            raise ValueError("LIBEREYE_BRACELET_ADDRESS and LIBEREYE_BRACELET_UUID must be set for BLE transport")
        return BleWristDriver(address=address, characteristic_uuid=uuid)
    raise ValueError(f"Unknown LIBEREYE_BRACELET_TRANSPORT value: {t!r}. Use 'mock', 'serial', or 'ble'.")


# Compatibility aliases for legacy hardware.py API
BraceletDriver = WristCueDriver
MockBraceletDriver = MockWristDriver
SerialBraceletDriver = SerialWristDriver
BleBraceletDriver = BleWristDriver
FallbackBraceletDriver = FallbackWristDriver
create_bracelet_driver = create_wrist_driver
