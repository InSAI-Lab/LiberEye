"""Unit tests for ScenePersistenceFSM and context change flag Delta_t.

Corresponds to ICASSP 2027 paper Section 2.2.
"""
from __future__ import annotations

from libereye.scene_persistence import ScenePersistenceFSM


def test_fsm_initial_state():
    fsm = ScenePersistenceFSM()
    assert fsm.state == "sidewalk"
    assert fsm.current_phase == "sidewalk"


def test_fsm_hysteresis_requires_3_consecutive_frames():
    fsm = ScenePersistenceFSM()
    # Frame 1: no transition, Delta_t = False
    state, delta_t = fsm.update("crossing")
    assert state == "sidewalk"
    assert delta_t is False

    # Frame 2: no transition, Delta_t = False
    state, delta_t = fsm.update("crossing")
    assert state == "sidewalk"
    assert delta_t is False

    # Frame 3: threshold met! Transitions to approaching_crossing, Delta_t = True!
    state, delta_t = fsm.update("crossing")
    assert state == "approaching_crossing"
    assert delta_t is True


def test_fsm_full_navigation_cycle():
    """sidewalk -> approaching_crossing -> crossing -> recovery -> sidewalk."""
    fsm = ScenePersistenceFSM()
    # 1. sidewalk -> approaching_crossing
    for _ in range(3):
        fsm.update("crossing")
    assert fsm.state == "approaching_crossing"

    # 2. approaching_crossing -> crossing
    for _ in range(3):
        fsm.update("crossing")
    assert fsm.state == "crossing"

    # 3. crossing -> recovery
    for _ in range(3):
        fsm.update("sidewalk")
    assert fsm.state == "recovery"

    # 4. recovery -> sidewalk
    for _ in range(3):
        fsm.update("sidewalk")
    assert fsm.state == "sidewalk"


def test_every_phase_transition_needs_a_fresh_evidence_window():
    fsm = ScenePersistenceFSM()
    for _ in range(3):
        fsm.update("crossing")
    assert fsm.update("crossing") == ("approaching_crossing", False)
    assert fsm.update("crossing") == ("approaching_crossing", False)
    assert fsm.update("crossing") == ("crossing", True)


def test_alternating_observations_never_satisfy_persistence():
    fsm = ScenePersistenceFSM()
    for _ in range(10):
        assert fsm.update("crossing") == ("sidewalk", False)
        assert fsm.update("sidewalk") == ("sidewalk", False)
