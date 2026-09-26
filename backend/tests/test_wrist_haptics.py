"""Unit tests for wrist haptics and Table 1 specifications.

Corresponds to ICASSP 2027 paper Section 2.3 and Table 1.
"""
from __future__ import annotations

import os

from libereye.models import HapticCue
from libereye.wrist_haptics import (
    TABLE1_WRIST_CUES,
    FallbackWristDriver,
    MockWristDriver,
    create_haptic_cue,
    create_wrist_driver,
    get_wrist_cue_profile,
)


def test_table1_specifications():
    """Verify all 7 wrist cues strictly match Table 1 parameters."""
    # D1: 3 to 5 m, Light, 0.15 s, 0.5 Hz
    d1 = TABLE1_WRIST_CUES["D1"]
    assert d1.meaning == "3 to 5 m"
    assert d1.intensity == "Light"
    assert d1.width_s == 0.15
    assert d1.timing == "0.5 Hz"

    # D2: 1.5 to 3 m, Light, 0.15 s, 1 Hz
    d2 = TABLE1_WRIST_CUES["D2"]
    assert d2.meaning == "1.5 to 3 m"
    assert d2.intensity == "Light"
    assert d2.width_s == 0.15
    assert d2.timing == "1 Hz"

    # D3: 0.8 to 1.5 m, Medium, 0.20 s, 2 Hz
    d3 = TABLE1_WRIST_CUES["D3"]
    assert d3.meaning == "0.8 to 1.5 m"
    assert d3.intensity == "Medium"
    assert d3.width_s == 0.20
    assert d3.timing == "2 Hz"

    # D4: Below 0.8 m, Medium, 0.20 s, 4 Hz
    d4 = TABLE1_WRIST_CUES["D4"]
    assert d4.meaning == "Below 0.8 m"
    assert d4.intensity == "Medium"
    assert d4.width_s == 0.20
    assert d4.timing == "4 Hz"

    # W1: Attention, Strong, 0.25 s, 2 pulses
    w1 = TABLE1_WRIST_CUES["W1"]
    assert w1.meaning == "Attention"
    assert w1.intensity == "Strong"
    assert w1.width_s == 0.25
    assert w1.timing == "2 pulses"

    # W2: Avoidance, Strong, 0.25 s, 3 + 3 pulses, 0.4 s gap
    w2 = TABLE1_WRIST_CUES["W2"]
    assert w2.meaning == "Avoidance"
    assert w2.intensity == "Strong"
    assert w2.width_s == 0.25
    assert w2.timing == "3 + 3 pulses, 0.4 s gap"

    # W3: Stop, Strong, 1 + 4 x 0.15, 1 long + 4 short
    w3 = TABLE1_WRIST_CUES["W3"]
    assert w3.meaning == "Stop"
    assert w3.intensity == "Strong"
    assert w3.width_s == 1.0


def test_create_haptic_cue_factory():
    """Verify create_haptic_cue builds correctly populated HapticCue dataclass."""
    cue = create_haptic_cue("W3")
    assert cue.device == "bracelet"
    assert cue.pattern == "W3"
    assert cue.intensity == 100
    assert cue.risk_level == "danger"
    assert "Emergency stop" in cue.meaning


def test_mock_wrist_driver():
    """Verify MockWristDriver captures sent cues."""
    driver = MockWristDriver()
    cue = create_haptic_cue("D2")
    driver.send(cue)
    assert driver.last_sent == cue


def test_fallback_wrist_driver_voice_compensation():
    """Section 2.3: Available speech can convey wrist warnings when wristband disconnects."""
    class FailingDriver:
        def send(self, cue: HapticCue) -> None:
            raise ConnectionError("BLE link lost")

    fallback = FallbackWristDriver(FailingDriver())
    cue = create_haptic_cue("W3")
    fallback.send(cue)

    assert fallback.connected is False
    msgs = fallback.pop_voice_messages()
    assert len(msgs) == 1
    assert "Haptic warning W3" in msgs[0]
    assert "Emergency stop" in msgs[0]


def test_create_wrist_driver_factory():
    """Verify driver creation by transport name."""
    mock_drv = create_wrist_driver("mock")
    assert isinstance(mock_drv, MockWristDriver)


def test_ble_command_matches_firmware_three_byte_protocol():
    from libereye.wrist_haptics import encode_wrist_command
    assert encode_wrist_command("D1") == bytes([1, 0x0B, 0xB8])
    assert encode_wrist_command("W3", 8000) == bytes([7, 0x1F, 0x40])
    assert encode_wrist_command(None) == bytes([0, 0, 0])
    import pytest
    for duration in (-1, 8001, 0.5, True):
        with pytest.raises(ValueError):
            encode_wrist_command("D1", duration)


def test_timing_profile_separates_paper_values_and_engineering_defaults():
    from libereye.wrist_haptics import wrist_timing_profile
    d1 = wrist_timing_profile("D1")
    assert create_haptic_cue("D1").frequency_hz == 0.5
    assert d1["pulse_widths_ms"] == [150]
    assert d1["gaps_ms"] == [1850]
    w2 = wrist_timing_profile("W2")
    assert w2["pulse_widths_ms"] == [250] * 6
    assert w2["gaps_ms"] == [250, 250, 400, 250, 250]
    assert "pulse_widths" not in w2["engineering_defaults"]
    assert "intra_group_gaps" in w2["engineering_defaults"]
    assert create_haptic_cue("W2").frequency_hz == 0
    w3 = wrist_timing_profile("W3")
    assert sum(w3["pulse_widths_ms"]) + sum(w3["gaps_ms"]) == 2250
    assert w3["amplitude_calibrated"] is False


def test_ordinal_intensity_matches_firmware_reference_amplitudes():
    from libereye.wrist_haptics import wrist_timing_profile
    expected = {
        "D1": (25, 32), "D2": (25, 32),
        "D3": (60, 76), "D4": (60, 76),
        "W1": (100, 127), "W2": (100, 127), "W3": (100, 127),
    }
    for pattern, (normalized, rtp) in expected.items():
        assert create_haptic_cue(pattern).intensity == normalized
        profile = wrist_timing_profile(pattern)
        assert profile["reference_intensity"] == normalized
        assert profile["reference_rtp"] == rtp
        assert profile["amplitude_calibrated"] is False


def test_all_warning_sequences_finish_at_firmware_durations():
    from libereye.wrist_haptics import wrist_timing_profile
    for pattern, duration_ms in {"W1": 750, "W2": 2900, "W3": 2250}.items():
        profile = wrist_timing_profile(pattern)
        assert not profile["repeat"]
        assert sum(profile["pulse_widths_ms"]) + sum(profile["gaps_ms"]) == duration_ms
        assert create_haptic_cue(pattern).frequency_hz == 0


def test_ble_bench_driver_keeps_connection_until_ack_and_completion(monkeypatch):
    import asyncio
    import sys
    import types
    from libereye.wrist_haptics import BleWristDriver, WRIST_STATUS_UUID
    events = []

    class FakeBleakClient:
        def __init__(self, address, **kwargs):
            assert address == "reference-board"

        async def __aenter__(self):
            events.append("connect")
            return self

        async def __aexit__(self, *args):
            events.append("disconnect")

        async def start_notify(self, uuid, callback):
            assert uuid == WRIST_STATUS_UUID
            self.notify = callback
            events.append("subscribe")

        async def write_gatt_char(self, uuid, payload, response):
            assert events[-1] == "subscribe"
            assert payload == bytes([7, 0x0B, 0xB8]) and response is True
            events.append("write")
            self.notify(None, bytearray(b"ACK 7 o"))
            self.notify(None, bytearray(b"k\n"))
            asyncio.get_running_loop().call_later(0.001, self.finish)

        def finish(self):
            assert "disconnect" not in events
            events.append("complete")
            self.notify(None, bytearray(b"EVT 7 done\n"))

    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakClient=FakeBleakClient))
    BleWristDriver("reference-board", "rx").send(create_haptic_cue("W3"))
    assert events == ["connect", "subscribe", "write", "complete", "disconnect"]


def test_ble_bench_driver_rejects_busy_and_driver_fault(monkeypatch):
    import sys
    import types
    import pytest
    from libereye.wrist_haptics import BleWristDriver

    class FakeBleakClient:
        outcome = b"ACK 7 busy\n"

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def start_notify(self, uuid, callback):
            self.notify = callback

        async def write_gatt_char(self, *args, **kwargs):
            self.notify(None, bytearray(self.outcome))

    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakClient=FakeBleakClient))
    driver = BleWristDriver("reference-board", "rx")
    with pytest.raises(RuntimeError, match="busy"):
        driver.send(create_haptic_cue("W3"))
    FakeBleakClient.outcome = b"ACK 7 driver\n"
    with pytest.raises(ConnectionError, match="driver"):
        driver.send(create_haptic_cue("W3"))
