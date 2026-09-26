"""Tests for HAPTIC-01..04: bracelet driver transport switching and disconnect fallback."""
from __future__ import annotations

import os

import pytest

from libereye.hardware import (
    BleBraceletDriver,
    FallbackBraceletDriver,
    MockBraceletDriver,
    SerialBraceletDriver,
    create_bracelet_driver,
)
from libereye.models import HapticCue
from libereye.mobility_coordinator import MobilityOrchestrator


# HAPTIC-01: Transport switching via env var
def test_create_bracelet_driver_mock(monkeypatch):
    """LIBEREYE_BRACELET_TRANSPORT=mock returns MockBraceletDriver."""
    monkeypatch.setenv("LIBEREYE_BRACELET_TRANSPORT", "mock")
    driver = create_bracelet_driver()
    assert isinstance(driver, MockBraceletDriver)


def test_create_bracelet_driver_default_is_mock(monkeypatch):
    """Default (no env var) returns MockBraceletDriver."""
    monkeypatch.delenv("LIBEREYE_BRACELET_TRANSPORT", raising=False)
    driver = create_bracelet_driver()
    assert isinstance(driver, MockBraceletDriver)


def test_create_bracelet_driver_explicit_mock():
    """Explicit 'mock' argument returns MockBraceletDriver."""
    driver = create_bracelet_driver("mock")
    assert isinstance(driver, MockBraceletDriver)


def test_create_bracelet_driver_unknown_raises():
    """Unknown transport value raises ValueError."""
    with pytest.raises(ValueError, match="Unknown LIBEREYE_BRACELET_TRANSPORT"):
        create_bracelet_driver("unknown_transport")


# HAPTIC-02: Vibration pattern enum
def test_haptic_cue_distance_pattern():
    """D-pattern constructs without error."""
    cue = HapticCue("bracelet", "D2", 1, 35, "warn", "Medium-distance approach")
    assert cue.pattern == "D2"


def test_haptic_cue_warning_pattern():
    """W-pattern constructs without error."""
    cue = HapticCue("bracelet", "W1", 8, 90, "warn", "Hazard warning")
    assert cue.pattern == "W1"


def test_haptic_cue_emergency_stop():
    """W3 emergency-stop pattern constructs without error."""
    cue = HapticCue("bracelet", "W3", 10, 100, "danger", "Emergency stop")
    assert cue.pattern == "W3"


def test_mock_driver_sends_distance_pattern(capsys):
    """MockBraceletDriver logs D-pattern."""
    driver = MockBraceletDriver()
    cue = HapticCue("bracelet", "D1", 1, 25, "info", "test")
    driver.send(cue)
    captured = capsys.readouterr()
    assert "D1" in captured.out
    assert "[bracelet]" in captured.out


def test_mock_driver_sends_emergency_stop(capsys):
    """MockBraceletDriver logs W3 pattern."""
    driver = MockBraceletDriver()
    cue = HapticCue("bracelet", "W3", 10, 100, "danger", "test")
    driver.send(cue)
    captured = capsys.readouterr()
    assert "W3" in captured.out


# HAPTIC-03: Disconnect fallback
class _FailingDriver:
    """Driver that always raises on send (simulates BLE disconnect)."""
    def send(self, cue: HapticCue) -> None:
        raise ConnectionError("BLE disconnected")


def test_fallback_driver_catches_disconnect():
    """FallbackBraceletDriver catches exception and stores voice message."""
    fallback = FallbackBraceletDriver(_FailingDriver())
    cue = HapticCue("bracelet", "W3", 10, 100, "danger", "High risk")
    fallback.send(cue)  # should NOT raise
    assert not fallback.connected
    msgs = fallback.pop_voice_messages()
    assert len(msgs) == 1
    assert "Wrist disconnected" in msgs[0] or "W3" in msgs[0] or "Emergency stop" in msgs[0]


def test_fallback_driver_reconnects_on_success():
    """FallbackBraceletDriver marks connected=True when send succeeds."""
    fallback = FallbackBraceletDriver(MockBraceletDriver())
    cue = HapticCue("bracelet", "D1", 1, 25, "info", "test")
    fallback.send(cue)
    assert fallback.connected


def test_fallback_driver_pop_clears_messages():
    """pop_voice_messages clears the pending list."""
    fallback = FallbackBraceletDriver(_FailingDriver())
    cue = HapticCue("bracelet", "D1", 1, 25, "info", "test")
    fallback.send(cue)
    msgs1 = fallback.pop_voice_messages()
    msgs2 = fallback.pop_voice_messages()
    assert len(msgs1) == 1
    assert len(msgs2) == 0


# HAPTIC-04: Orchestrator decoupling
def test_orchestrator_accepts_bracelet_driver():
    """MobilityOrchestrator accepts bracelet_driver parameter."""
    driver = MockBraceletDriver()
    orch = MobilityOrchestrator(bracelet_driver=driver)
    assert orch.bracelet_driver is driver


def test_orchestrator_default_bracelet_driver_is_none():
    """MobilityOrchestrator default bracelet_driver is None (not imported directly)."""
    orch = MobilityOrchestrator()
    # bracelet_driver is None by default: orchestrator does not import concrete drivers
    assert orch.bracelet_driver is None


def test_orchestrator_does_not_import_concrete_drivers():
    """mobility_coordinator.py must not import MockBraceletDriver, SerialBraceletDriver, or BleBraceletDriver."""
    import libereye.mobility_coordinator as orch_module
    # Check module-level names: concrete driver classes should not be imported
    assert not hasattr(orch_module, "MockBraceletDriver"), "orchestrator should not import MockBraceletDriver"
    assert not hasattr(orch_module, "SerialBraceletDriver"), "orchestrator should not import SerialBraceletDriver"
    assert not hasattr(orch_module, "BleBraceletDriver"), "orchestrator should not import BleBraceletDriver"
