from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

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
    """Parses newline-delimited BLE messages from camera glasses.

    Recommended low-latency packet:
    {"type":"perception","payload":{...PerceptionFrame fields...}}\n

    Optional low-frame-rate image packet sequence:
    {"type":"jpeg_start","frame_id":"1","target_query":"cup"}\n
    {"type":"jpeg_chunk","frame_id":"1","data":"...base64..."}\n
    {"type":"jpeg_end","frame_id":"1"}\n
    """

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
    ) -> None:
        self.runtime = runtime or MobilityRuntime()
        self.media_analyzer = media_analyzer or MediaAnalyzer()

    def process(self, message: GlassesMessage) -> AssistancePlan:
        if isinstance(message, GlassesPerceptionMessage):
            return self.runtime.process_frame(message.frame)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(message.image_bytes)
            image_path = Path(tmp.name)
        try:
            frame, _ = self.media_analyzer.analyze_file(image_path, target_query=message.target_query)
            return self.runtime.process_frame(frame)
        finally:
            image_path.unlink(missing_ok=True)


class GlassesWifiReceiver:
    """WiFi frame receiver for PCPZ M02 Ultra glasses.

    The glasses act as an HTTP client and POST JPEG frames to /api/glasses/frame.
    This class tracks connection state and provides the frame ingestion pipeline.

    Usage:
        receiver = GlassesWifiReceiver(media_analyzer=analyzer)
        frame, evidence = receiver.ingest_jpeg(jpeg_bytes, target_query=None)
        # Check receiver.connected for fallback routing
    """

    DISCONNECT_TIMEOUT_S = 5.0

    def __init__(
        self,
        media_analyzer: MediaAnalyzer | None = None,
        disconnect_timeout_s: float = DISCONNECT_TIMEOUT_S,
    ) -> None:
        self.media_analyzer = media_analyzer or MediaAnalyzer()
        self.disconnect_timeout_s = disconnect_timeout_s
        self._last_frame_time: float | None = None
        self.connected: bool = False

    def ingest_jpeg(self, jpeg_bytes: bytes, target_query: str | None = None) -> tuple[PerceptionFrame, dict]:
        """Ingest a JPEG frame from the glasses WiFi stream.

        Returns (PerceptionFrame, evidence_dict): same contract as MediaAnalyzer.analyze_file.
        Updates self.connected = True and records last frame timestamp.
        """
        self._last_frame_time = time.time()
        self.connected = True

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(jpeg_bytes)
            image_path = Path(tmp.name)
        try:
            frame, evidence = self.media_analyzer.analyze_file(image_path, target_query=target_query)
            evidence["glasses_source"] = "wifi"
            return frame, evidence
        finally:
            image_path.unlink(missing_ok=True)

    def check_timeout(self) -> bool:
        """Check if glasses have timed out (no frames received within disconnect_timeout_s).

        Returns True if timed out (sets self.connected = False), False if still connected.
        """
        if self._last_frame_time is None:
            return False
        elapsed = time.time() - self._last_frame_time
        if elapsed > self.disconnect_timeout_s:
            self.connected = False
            return True
        return False


class BleGlassesClient:
    """BLE notification client for camera glasses.

    The phone implementation should mirror this protocol with CoreBluetooth:
    subscribe to the glasses notify characteristic, feed notification bytes to
    `GlassesBleParser`, then process the resulting messages.
    """

    def __init__(self, address: str, notify_characteristic_uuid: str) -> None:
        self.address = address
        self.notify_characteristic_uuid = notify_characteristic_uuid
        self.parser = GlassesBleParser()

    async def run(self, on_message: Callable[[GlassesMessage], None]) -> None:
        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise RuntimeError("bleak is required for BleGlassesClient") from exc

        def handle_notification(_: int, data: bytearray) -> None:
            for message in self.parser.feed(bytes(data)):
                on_message(message)

        async with BleakClient(self.address) as client:
            await client.start_notify(self.notify_characteristic_uuid, handle_notification)
            while True:
                await asyncio.sleep(1)
