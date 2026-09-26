from __future__ import annotations

import json
import os
import asyncio
from dataclasses import asdict
from typing import Protocol

from .models import HapticCue


class BraceletDriver(Protocol):
    def send(self, cue: HapticCue) -> None:
        raise NotImplementedError


class MockBraceletDriver:
    """Development driver that prints commands instead of touching hardware."""

    def send(self, cue: HapticCue) -> None:
        print("[bracelet]", json.dumps(asdict(cue), ensure_ascii=False))


class SerialBraceletDriver:
    """Serial protocol placeholder for Arduino/ESP32 bracelet firmware.

    Install pyserial before using this driver:
    pip install pyserial
    """

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for SerialBraceletDriver") from exc
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


class BleBraceletDriver:
    """Bluetooth LE bracelet driver.

    The firmware should expose a writable characteristic that accepts a UTF-8
    JSON command with D1-D4/W1-W3 pattern, frequency, intensity, and risk level.
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
            raise RuntimeError("bleak is required for BleBraceletDriver") from exc

        payload = {
            "pattern": cue.pattern,
            "frequency_hz": cue.frequency_hz,
            "intensity": cue.intensity,
            "risk_level": cue.risk_level,
            "meaning": cue.meaning,
        }
        async with BleakClient(self.address) as client:
            await client.write_gatt_char(self.characteristic_uuid, json.dumps(payload).encode("utf-8"))


class FallbackBraceletDriver:
    """Wraps another driver and falls back to voice description on disconnect.

    When the underlying driver raises an exception (e.g., BLE disconnect),
    the HapticCue is converted to a voice description and stored in
    `self.pending_voice_messages` for the orchestrator to append to voice_message.
    """

    def __init__(self, driver: BraceletDriver) -> None:
        self._driver = driver
        self.pending_voice_messages: list[str] = []
        self.connected: bool = True

    def send(self, cue: HapticCue) -> None:
        try:
            self._driver.send(cue)
            self.connected = True
        except Exception:
            self.connected = False
            # Convert HapticCue to voice description
            pattern_desc = {
                "D1": "Distant approach cue",
                "D2": "Medium-distance approach cue",
                "D3": "Close-distance cue",
                "D4": "Very-close-distance cue",
                "W1": "Hazard warning cue",
                "W2": "Immediate avoidance warning",
                "W3": "Emergency stop warning",
            }.get(cue.pattern, "Vibration cue")
            voice_desc = f"[Wrist disconnected] {pattern_desc}: {cue.meaning}"
            self.pending_voice_messages.append(voice_desc)
            print(f"[bracelet-fallback] {voice_desc}")

    def pop_voice_messages(self) -> list[str]:
        msgs = list(self.pending_voice_messages)
        self.pending_voice_messages.clear()
        return msgs


def create_bracelet_driver(transport: str | None = None) -> BraceletDriver:
    """Factory function that creates a bracelet driver based on LIBEREYE_BRACELET_TRANSPORT.

    Supported values:
    - "mock" (default): MockBraceletDriver: prints commands, no hardware needed
    - "serial": SerialBraceletDriver: requires LIBEREYE_BRACELET_PORT env var
    - "ble": BleBraceletDriver: requires LIBEREYE_BRACELET_ADDRESS and LIBEREYE_BRACELET_UUID env vars
    """
    t = (transport or os.getenv("LIBEREYE_BRACELET_TRANSPORT", "mock")).lower()
    if t == "mock":
        return MockBraceletDriver()
    if t == "serial":
        port = os.getenv("LIBEREYE_BRACELET_PORT", "/dev/ttyUSB0")
        baudrate = int(os.getenv("LIBEREYE_BRACELET_BAUDRATE", "115200"))
        return SerialBraceletDriver(port=port, baudrate=baudrate)
    if t == "ble":
        address = os.getenv("LIBEREYE_BRACELET_ADDRESS", "")
        uuid = os.getenv("LIBEREYE_BRACELET_UUID", "")
        if not address or not uuid:
            raise ValueError("LIBEREYE_BRACELET_ADDRESS and LIBEREYE_BRACELET_UUID must be set for BLE transport")
        return BleBraceletDriver(address=address, characteristic_uuid=uuid)
    raise ValueError(f"Unknown LIBEREYE_BRACELET_TRANSPORT value: {t!r}. Use 'mock', 'serial', or 'ble'.")


# Table 1 wrist haptics re-exports
from .wrist_haptics import (
    TABLE1_WRIST_CUES,
    WRIST_CUE_PRIORITY_ORDER,
    WRIST_CUE_PRIORITY_RANK,
    WristCueProfile,
    create_haptic_cue,
    create_wrist_driver,
    get_wrist_cue_profile,
)
