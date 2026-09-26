from __future__ import annotations

from typing import Dict, Literal

PhaseType = Literal["sidewalk", "approaching_crossing", "crossing", "recovery"]

# Valid phase transitions (Section 2.2)
PHASE_TRANSITIONS: Dict[str, Dict[str, str]] = {
    "sidewalk": {
        "sidewalk": "sidewalk",
        "street": "sidewalk",
        "crossing": "approaching_crossing",
        "blocked": "sidewalk",
        "finding": "sidewalk",
        "transit": "sidewalk",
        "indoor": "sidewalk",
        "unknown": "sidewalk",
    },
    "approaching_crossing": {
        "sidewalk": "sidewalk",
        "street": "sidewalk",
        "crossing": "crossing",
        "blocked": "sidewalk",
        "finding": "sidewalk",
        "transit": "sidewalk",
        "indoor": "sidewalk",
        "unknown": "approaching_crossing",
    },
    "crossing": {
        "sidewalk": "recovery",
        "street": "recovery",
        "crossing": "crossing",
        "blocked": "recovery",
        "finding": "recovery",
        "transit": "recovery",
        "indoor": "recovery",
        "unknown": "crossing",
    },
    "recovery": {
        "sidewalk": "sidewalk",
        "street": "sidewalk",
        "crossing": "approaching_crossing",
        "blocked": "sidewalk",
        "finding": "sidewalk",
        "transit": "sidewalk",
        "indoor": "sidewalk",
        "unknown": "recovery",
    },
}


class ScenePersistenceFSM:
    """Scene-state persistence FSM (Section 2.2).

    Limits rapid switching between sidewalk, approaching-crossing, crossing,
    and recovery phases using hysteresis (requiring N consecutive frames).
    Tracks phase transitions to determine context change flag Delta_t.
    """

    # Engineering default; the paper does not specify a frame count.
    HYSTERESIS_N = 3

    def __init__(self, initial_state: str = "sidewalk") -> None:
        if initial_state not in PHASE_TRANSITIONS:
            raise ValueError(f"Unknown scene phase: {initial_state}")
        self.state: str = initial_state
        self._candidate: str = initial_state
        self._candidate_count: int = 0
        self._last_state: str = initial_state

    def update(self, scene_type: str) -> tuple[str, bool]:
        """Update FSM with incoming scene_type observation.

        Returns:
            tuple[str, bool]: (current_fsm_phase, context_change_flag_delta_t)
        """
        normalized = scene_type if scene_type in PHASE_TRANSITIONS.get(self.state, {}) else "unknown"

        if normalized == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = normalized
            self._candidate_count = 1

        context_change = False
        if self._candidate_count >= self.HYSTERESIS_N:
            next_state = PHASE_TRANSITIONS.get(self.state, {}).get(normalized, self.state)
            if next_state != self.state:
                context_change = True
                self._last_state = self.state
                self.state = next_state
                # Each transition needs its own evidence window.
                self._candidate_count = 0

        return self.state, context_change

    @property
    def current_phase(self) -> str:
        return self.state
