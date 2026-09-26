from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union

from .media_analyzer import MediaAnalyzer
from .models import AssistancePlan, PerceptionFrame
from .runtime import MobilityRuntime


@dataclass(frozen=True)
class GlassesPerceptionMessage:
    frame: PerceptionFrame


@dataclass(frozen=True)
class GlassesImageMessage:
    frame_id: str
    image_bytes: bytes
    target_query: str | None = None


GlassesMessage = Union[GlassesPerceptionMessage, GlassesImageMessage]


class GlassesBleParser:
    """Parses newline-delimited BLE messages from camera glasses."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._image_chunks: dict[str, list[bytes]] = {}
        self._image_targets: dict[str, str | None] = {}

    def feed(self, data: bytes) -> list[GlassesMessage]:
        self._buffer.extend(data)
        messages: list[GlassesMessage] = []

        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            if not line.strip():
                continue
            message = self._parse_line(line)
            if message:
                messages.append(message)
        return messages

    def _parse_line(self, line: bytes) -> GlassesMessage | None:
        packet = json.loads(line.decode("utf-8"))
        packet_type = packet.get("type", "perception")

        if packet_type == "perception":
            payload = packet.get("payload", packet)
            payload.pop("type", None)
            return GlassesPerceptionMessage(PerceptionFrame(**payload))

        if packet_type == "jpeg_start":
            frame_id = str(packet["frame_id"])
            self._image_chunks[frame_id] = []
            self._image_targets[frame_id] = packet.get("target_query")
            return None

        if packet_type == "jpeg_chunk":
            frame_id = str(packet["frame_id"])
            if frame_id not in self._image_chunks:
                self._image_chunks[frame_id] = []
            self._image_chunks[frame_id].append(base64.b64decode(packet["data"]))
            return None

        if packet_type == "jpeg_end":
            frame_id = str(packet["frame_id"])
            chunks = self._image_chunks.pop(frame_id, [])
            target_query = self._image_targets.pop(frame_id, None)
            if not chunks:
                return None
            return GlassesImageMessage(frame_id=frame_id, image_bytes=b"".join(chunks), target_query=target_query)

        raise ValueError(f"Unsupported glasses packet type: {packet_type}")


class GlassesMessageProcessor:
    def __init__(
        self,
        runtime: MobilityRuntime | None = None,
        media_analyzer: MediaAnalyzer | None = None,
        plan_callback: Callable[[AssistancePlan], None] | None = None,
    ) -> None:
        self.runtime = runtime or MobilityRuntime()
        self.media_analyzer = media_analyzer or MediaAnalyzer()
        self.plan_callback = plan_callback

    def handle_message(self, message: GlassesMessage) -> AssistancePlan:
        if isinstance(message, GlassesPerceptionMessage):
            plan = self.runtime.process_perception(message.frame)
            if self.plan_callback:
                self.plan_callback(plan)
            return plan

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(message.image_bytes)
            tmp_path = Path(tmp.name)

        try:
            frame, _ = self.media_analyzer.analyze_file(tmp_path, target_query=message.target_query)
            plan = self.runtime.process_perception(frame)
            if self.plan_callback:
                self.plan_callback(plan)
            return plan
        finally:
            tmp_path.unlink(missing_ok=True)


class CameraGlassesReceiver:
    """Egocentric camera glasses receiver and phone camera fallback (Section 2.1, 2.3).

    'Phone-camera input replaces missing glasses frames. Inference still requires the backend.'
    """

    def __init__(
        self,
        media_analyzer: MediaAnalyzer | None = None,
        timeout_s: float = 3.0,
    ) -> None:
        self.media_analyzer = media_analyzer or MediaAnalyzer()
        self.timeout_s = timeout_s
        self.last_frame_time: float | None = None

    @property
    def connected(self) -> bool:
        if self.last_frame_time is None:
            return False
        return (time.time() - self.last_frame_time) <= self.timeout_s

    def ingest_jpeg(
        self,
        jpeg_bytes: bytes,
        target_query: str | None = None,
    ) -> Tuple[PerceptionFrame, Dict[str, Any]]:
        self.last_frame_time = time.time()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(jpeg_bytes)
            tmp_path = Path(tmp.name)

        try:
            return self.media_analyzer.analyze_file(tmp_path, target_query=target_query)
        finally:
            tmp_path.unlink(missing_ok=True)

    def handle_phone_camera_fallback(
        self,
        jpeg_bytes: bytes,
        target_query: str | None = None,
    ) -> Tuple[PerceptionFrame, Dict[str, Any]]:
        """Processes smartphone camera frames when glasses frames are missing."""
        frame, evidence = self.ingest_jpeg(jpeg_bytes, target_query=target_query)
        evidence["camera_source"] = "phone_camera_fallback"
        return frame, evidence


# Compatibility alias
GlassesWifiReceiver = CameraGlassesReceiver
