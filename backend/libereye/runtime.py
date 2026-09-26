from __future__ import annotations

from dataclasses import asdict

from .hardware import BraceletDriver, MockBraceletDriver
from .models import AssistancePlan, PerceptionFrame
from .mobility_coordinator import MobilityOrchestrator


class MobilityRuntime:
    """End-to-end runtime loop for deployable integrations."""

    def __init__(
        self,
        orchestrator: MobilityOrchestrator | None = None,
        bracelet: BraceletDriver | None = None,
    ) -> None:
        self.orchestrator = orchestrator or MobilityOrchestrator()
        self.bracelet = bracelet or MockBraceletDriver()

    def process_frame(self, frame: PerceptionFrame, send_haptic: bool = True) -> AssistancePlan:
        plan = self.orchestrator.analyze_perception(frame)
        if send_haptic and plan.haptics:
            self.bracelet.send(plan.haptics[0])
        return plan

    def process_frame_dict(self, payload: dict, send_haptic: bool = True) -> dict:
        plan = self.process_frame(PerceptionFrame(**payload), send_haptic=send_haptic)
        return asdict(plan)
